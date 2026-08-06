"""Learner Model — 分析引擎

聚合所有数据源，生成学习者画像。

设计原则：
  - 只读不写：不修改任何数据源
  - 纯聚合：不参与决策，不生成推送内容
  - 可审计：每份报告都有完整的数据来源追溯
"""
from __future__ import annotations
import json, os, re, datetime
from collections import defaultdict
from typing import Optional
from dataclasses import dataclass, field

from config import DATA_DIR, KB_PATH, DAILY_RECORD_DIR
from learner.context import current_user_id
from learner import paths as P

# ── 数据源 ──
def _answer_log_path() -> str:
    try:
        return P.answer_log_path()
    except Exception:
        return os.path.join(DATA_DIR, "answer-log.jsonl")

# BIG-TEACH-012d #16: learning-progress.json 已退役。所有分析基于 answer-log。


@dataclass
class ErrorPattern:
    pattern: str
    kps: list[str]
    count: int
    examples: list[str] = field(default_factory=list)


@dataclass
class KPTrend:
    name: str
    mastery_before: float = 0.0
    mastery_after: float = 0.0
    opportunity_count: int = 0
    last_seen: str = ""


@dataclass
class WeeklyProfile:
    period_start: str
    period_end: str
    kp_trends: list[KPTrend]
    error_patterns: list[ErrorPattern]
    weak_chains: list[dict]
    engagement: dict
    subjects_progress: dict
    summary: str = ""


# ── 数据加载 ──

def load_bkt_log() -> list[dict]:
    try:
        with open(_answer_log_path(), "r", encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except Exception:
        return []


def load_daily_records(days: int = 7) -> str:
    """读取最近 N 天题目索引精简列表（不加载全文，避免爆 token）。"""
    try:
        from record_index import list_recent
        rows = list_recent(DAILY_RECORD_DIR, days)
        if not rows:
            return ""
        lines = [f"最近 {days} 天共 {len(rows)} 条："]
        for r in rows:
            lines.append(
                f"- {r.get('date')} #{r.get('num')} {r.get('subject')}/{r.get('difficulty')} "
                f"| {r.get('kp') or '-'} | {r.get('ref_source') or ''}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


# ── 分析函数 ──

def _is_applied_learning_record(r: dict) -> bool:
    """是否有效学习记录（audit/pending/未应用/无 mastery 均跳过）。"""
    if r.get("status") in ("audit", "pending"):
        return False
    if r.get("update_applied") is False:
        return False
    kp = r.get("knowledge_point")
    if not kp:
        return False
    # mastery 缺失视为无效（adjust_difficulty audit 等日志会缺 mastery）
    if r.get("mastery_before") is None and r.get("mastery_after") is None:
        return False
    return True


def analyze_kp_trends(bkt_log: list[dict]) -> list[KPTrend]:
    """BKT 掌握度变化趋势（仅基于有效学习记录，跳过 audit/pending/无 mastery）。"""
    latest = {}
    first = {}
    for r in bkt_log:
        if not _is_applied_learning_record(r):
            continue
        kp = r.get("knowledge_point")
        if kp not in first:
            first[kp] = r.get("mastery_before") or 0
        latest[kp] = r.get("mastery_after") or 0

    kp_occurrences: dict[str, int] = defaultdict(int)
    kp_last_seen: dict[str, str] = {}
    for r in bkt_log:
        if not _is_applied_learning_record(r):
            continue
        kp = r.get("knowledge_point")
        kp_occurrences[kp] += 1
        ts = r.get("ts", "")
        if ts and (kp not in kp_last_seen or ts > kp_last_seen[kp]):
            kp_last_seen[kp] = ts[:10]

    trends = []
    for kp in sorted(set(latest.keys()) | set(first.keys())):
        trends.append(KPTrend(
            name=kp,
            mastery_before=first.get(kp, 0),
            mastery_after=latest.get(kp, 0),
            opportunity_count=kp_occurrences.get(kp, 0),
            last_seen=kp_last_seen.get(kp, ""),
        ))
    return trends


def analyze_error_patterns(bkt_log: list[dict]) -> list[ErrorPattern]:
    """从 answer-log 中提取薄弱知识点（近 7 天多次答错或掌握度低）。"""
    from collections import defaultdict
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(days=7)).isoformat()

    fail_by_kp: dict[str, list[str]] = defaultdict(list)
    for r in bkt_log:
        ts = r.get("ts", "")
        if ts and ts < cutoff:
            continue
        kp = r.get("knowledge_point")
        if not kp:
            continue
        if r.get("correct") is False:
            fail_by_kp[kp].append(r.get("conv_tag", ""))

    patterns = []
    for kp, examples in sorted(fail_by_kp.items(), key=lambda x: -len(x[1])):
        if len(examples) >= 2:
            patterns.append(ErrorPattern(
                pattern=f"{kp} 近期答错 {len(examples)} 次",
                kps=[kp],
                count=len(examples),
                examples=examples[:3],
            ))

    # 若有 BKT mastery 数据，补充掌握度极低的知识点
    try:
        bkt_logger = _get_bkt_logger()
        if bkt_logger and hasattr(bkt_logger, 'get_all_kp_mastery'):
            mastery = bkt_logger.get_all_kp_mastery(current_user_id()) or {}
            for kp, val in sorted(mastery.items(), key=lambda x: x[1]):
                if val < 0.3 and not any(kp in p.kps for p in patterns):
                    patterns.append(ErrorPattern(
                        pattern=f"{kp} 掌握度仅 {val:.0%}",
                        kps=[kp],
                        count=1,
                    ))
    except Exception:
        pass

    return patterns


def _get_bkt_logger():
    """Lazy-init BKTLogger for mastery queries."""
    try:
        from bkt import BKTLogger
        return BKTLogger(_answer_log_path())
    except Exception:
        return None


def analyze_weak_chains(lp_retired: bool = True) -> list[dict]:
    """learning-progress.json 已退役（BIG-TEACH-012d #16），章节级进度不可用。"""
    return []


def analyze_engagement(bkt_log: list[dict]) -> dict:
    """近 7 天交互统计（基于 answer-log）。"""
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)

    recent = [r for r in bkt_log if r.get("ts", "") >= week_ago.strftime("%Y-%m-%d")]
    total = len(recent)
    correct = sum(1 for r in recent if r.get("correct") is True)
    incorrect = sum(1 for r in recent if r.get("correct") is False)

    return {
        "total_pushes": total,
        "reply_rate": round(correct / total, 2) if total else 0,
        "correct": correct,
        "incorrect": incorrect,
        "silent_days": 0,
        "note": "基于 answer-log（learning-progress 已退役）",
    }


def analyze_subjects_progress(lp_retired: bool = True) -> dict:
    """learning-progress.json 已退役（BIG-TEACH-012d #16），科目章节进展不可用。"""
    return {}


# ── 主入口 ──

def analyze(weeks: int = 1) -> WeeklyProfile:
    """执行一次完整分析，返回周报。

    所有分析基于 answer-log（BIG-TEACH-012d #16: learning-progress.json 已退役）。
    """
    bkt_log = load_bkt_log()
    now = datetime.datetime.now()
    start = (now - datetime.timedelta(days=7 * weeks)).strftime("%Y-%m-%d")

    kp_trends = analyze_kp_trends(bkt_log)
    error_patterns = analyze_error_patterns(bkt_log)
    weak_chains = analyze_weak_chains()
    engagement = analyze_engagement(bkt_log)
    subjects_progress = analyze_subjects_progress()

    # LLM 总结（pro+thinking，一周一次）
    summary = ""
    if kp_trends or error_patterns:
        try:
            from decide.router import call_llm
            context = _build_llm_context(kp_trends, error_patterns, weak_chains, engagement, subjects_progress)
            summary = call_llm(
                system="你是一个教学分析师。根据以下学习数据，写一段200字以内的周度培养建议。"
                       "指出最需要关注的1-2个薄弱点、建议的改进方向、以及下一周的学习策略。"
                       "语气直接、具体，不要空话。",
                user=context,
                task_type="generate", difficulty="challenge",
            )
        except Exception as e:
            summary = f"[分析完成，LLM 总结失败: {e}]"

    return WeeklyProfile(
        period_start=start,
        period_end=now.strftime("%Y-%m-%d"),
        kp_trends=kp_trends,
        error_patterns=error_patterns,
        weak_chains=weak_chains,
        engagement=engagement,
        subjects_progress=subjects_progress,
        summary=summary,
    )


def _build_llm_context(kp_trends, error_patterns, weak_chains, engagement, subjects_progress) -> str:
    """把结构化数据拼成 LLM 能读的文本。"""
    lines = ["## 掌握度变化"]
    for t in kp_trends:
        lines.append(f"- {t.name}: {t.mastery_before:.0%} → {t.mastery_after:.0%} ({t.opportunity_count}次)")

    if error_patterns:
        lines.append("\n## 薄弱点")
        for p in error_patterns:
            lines.append(f"- {p.pattern} (出现{p.count}次)")

    if weak_chains:
        lines.append("\n## 进度瓶颈")
        for c in weak_chains:
            lines.append(f"- {c['chain']}")

    lines.append(f"\n## 交互")
    lines.append(f"推送{engagement['total_pushes']}次，正确{engagement.get('correct', 0)}次，错误{engagement.get('incorrect', 0)}次")

    if subjects_progress:
        lines.append("\n## 科目进展")
        for subj, info in subjects_progress.items():
            lines.append(f"- {subj}: {info['progress']} (进行中{info['in_progress']}章)")
    else:
        lines.append("\n## 科目进展")
        lines.append("（learning-progress 已退役，章节级进度暂不可用）")

    return "\n".join(lines)
