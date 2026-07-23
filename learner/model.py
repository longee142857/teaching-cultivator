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

from config import DATA_DIR, KB_PATH, LP_PATH, DAILY_RECORD_DIR

# ── 数据源 ──
ANSWER_LOG = os.path.join(DATA_DIR, "answer-log.jsonl")


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

def load_learning_progress() -> dict:
    try:
        with open(LP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_bkt_log() -> list[dict]:
    try:
        with open(ANSWER_LOG, "r", encoding="utf-8") as f:
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

def analyze_kp_trends(bkt_log: list[dict], lp: dict) -> list[KPTrend]:
    """BKT 掌握度变化趋势。"""
    # 从 answer-log.jsonl
    latest = {}
    first = {}
    for r in bkt_log:
        kp = r.get("knowledge_point")
        if not kp:
            continue
        if kp not in first:
            first[kp] = r.get("mastery_after", 0)
        latest[kp] = r.get("mastery_after", 0)

    # 补充 learning-progress.json 中 problemsDone 的掌握度标记
    done_mastery = defaultdict(list)
    for pd in lp.get("problemsDone", []):
        for kp, label in pd.get("mastery", {}).items():
            score = {"passed": 0.85, "weak-path": 0.4, "weak-usage": 0.35, "failed": 0.15}.get(label, 0.5)
            done_mastery[kp].append(score)

    trends = []
    all_kps = set(latest.keys()) | set(done_mastery.keys())
    for kp in sorted(all_kps):
        trends.append(KPTrend(
            name=kp,
            mastery_before=first.get(kp, 0),
            mastery_after=latest.get(kp, max(done_mastery.get(kp, [0]))),
            opportunity_count=sum(1 for r in bkt_log if r.get("knowledge_point") == kp),
            last_seen=bkt_log[-1].get("ts", "")[:10] if bkt_log else "",
        ))
    return trends


def analyze_error_patterns(lp: dict) -> list[ErrorPattern]:
    """从 problemsDone 中提取错误模式。"""
    patterns = []
    weak_by_kp = defaultdict(list)

    for pd in lp.get("problemsDone", []):
        mastery = pd.get("mastery", {})
        for kp, label in mastery.items():
            if label in ("weak-path", "weak-usage", "failed"):
                weak_by_kp[kp].append(pd.get("topic", ""))

    for kp, examples in weak_by_kp.items():
        patterns.append(ErrorPattern(
            pattern=f"{kp} 需要加强",
            kps=[kp],
            count=len(examples),
            examples=examples[:3],
        ))

    return patterns


def analyze_weak_chains(lp: dict) -> list[dict]:
    """从 subject 章节进度的 🔄 状态推断薄弱链路。"""
    chains = []
    for subj, info in lp.get("subjects", {}).items():
        in_progress = [ch for ch, st in info.get("chapters", {}).items() if "🔄" in st]
        if len(in_progress) >= 2:
            chains.append({
                "chain": " → ".join(in_progress[:3]),
                "subject": subj,
            })
    return chains


def analyze_engagement(lp: dict) -> dict:
    """近 7 天交互统计。"""
    sent = lp.get("problemsSent", [])
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)

    recent = [p for p in sent if p.get("date", "").startswith(week_ago.strftime("%Y-%m-%d"))]
    total = len(recent)
    replied = sum(1 for p in recent if p.get("response", "").strip())

    return {
        "total_pushes": total,
        "reply_rate": round(replied / total, 2) if total else 0,
        "silent_days": 0,  # TODO: 计算连续无回复天数
    }


def analyze_subjects_progress(lp: dict) -> dict:
    """各科目章节进展。"""
    result = {}
    for subj, info in lp.get("subjects", {}).items():
        chapters = info.get("chapters", {})
        done = sum(1 for s in chapters.values() if "✅" in s or "掌握" in s)
        pend = sum(1 for s in chapters.values() if "🔄" in s)
        total = len(chapters)
        result[subj] = {
            "progress": f"{done}/{total}",
            "in_progress": pend,
            "level": info.get("level", ""),
        }
    return result


# ── 主入口 ──

def analyze(weeks: int = 1) -> WeeklyProfile:
    """执行一次完整分析，返回周报。"""
    lp = load_learning_progress()
    bkt_log = load_bkt_log()
    now = datetime.datetime.now()
    start = (now - datetime.timedelta(days=7 * weeks)).strftime("%Y-%m-%d")

    kp_trends = analyze_kp_trends(bkt_log, lp)
    error_patterns = analyze_error_patterns(lp)
    weak_chains = analyze_weak_chains(lp)
    engagement = analyze_engagement(lp)
    subjects_progress = analyze_subjects_progress(lp)

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
    lines.append(f"推送{engagement['total_pushes']}次，回复率{engagement['reply_rate']:.0%}")

    lines.append("\n## 科目进展")
    for subj, info in subjects_progress.items():
        lines.append(f"- {subj}: {info['progress']} (进行中{info['in_progress']}章)")

    return "\n".join(lines)
