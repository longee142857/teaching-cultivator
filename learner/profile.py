"""Learner Profile — 长期画像持久化

每周写入一份完整画像到 data/learner-profile/。
"""
from __future__ import annotations
import json, os, datetime

from config import DATA_DIR
from learner.model import analyze, WeeklyProfile, KPTrend, ErrorPattern

PROFILE_DIR = os.path.join(DATA_DIR, "learner-profile")


def ensure_dir():
    os.makedirs(PROFILE_DIR, exist_ok=True)


def build_weekly(weeks: int = 1) -> WeeklyProfile:
    """执行分析，写入文件，返回结果。"""
    ensure_dir()
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    m = analyze(weeks=weeks)

    # 写入 JSON
    json_path = os.path.join(PROFILE_DIR, f"weekly-{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_profile_to_dict(m), f, ensure_ascii=False, indent=2)

    # 写入可读 Markdown
    md_path = os.path.join(PROFILE_DIR, f"weekly-{date_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_format_md(m))

    # 更新 latest
    latest_path = os.path.join(PROFILE_DIR, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(_profile_to_dict(m), f, ensure_ascii=False, indent=2)

    return m


def _profile_to_dict(p: WeeklyProfile) -> dict:
    return {
        "period": {"start": p.period_start, "end": p.period_end},
        "kp_trends": [{"name": t.name, "mastery_before": t.mastery_before,
                        "mastery_after": t.mastery_after, "count": t.opportunity_count}
                       for t in p.kp_trends],
        "error_patterns": [{"pattern": ep.pattern, "kps": ep.kps, "count": ep.count}
                           for ep in p.error_patterns],
        "weak_chains": p.weak_chains,
        "engagement": p.engagement,
        "subjects_progress": p.subjects_progress,
        "summary": p.summary,
    }


def _format_md(p: WeeklyProfile) -> str:
    lines = [f"# 周报 {p.period_start} ~ {p.period_end}", ""]

    if p.summary:
        lines.append("## 培养建议")
        lines.append(p.summary)
        lines.append("")

    if p.kp_trends:
        lines.append("## 掌握度变化")
        for t in p.kp_trends:
            mb = t.mastery_before or 0
            ma = t.mastery_after or 0
            arrow = "↑" if ma > mb else "↓" if ma < mb else "→"
            lines.append(f"- {t.name} {mb:.0%} {arrow} {ma:.0%} ({t.opportunity_count}次)")
        lines.append("")

    if p.error_patterns:
        lines.append("## 薄弱点")
        for ep in p.error_patterns:
            lines.append(f"- {ep.pattern} ({ep.count}次)")
        lines.append("")

    if p.weak_chains:
        lines.append("## 进度瓶颈")
        for c in p.weak_chains:
            lines.append(f"- {c['chain']}")
        lines.append("")

    lines.append("## 交互统计")
    lines.append(f"- 总推送: {p.engagement.get('total_pushes', 0)}")
    lines.append(f"- 回复率: {p.engagement.get('reply_rate', 0):.0%}")

    lines.append("")
    lines.append("## 科目进展")
    for subj, info in p.subjects_progress.items():
        lines.append(f"- {subj}: {info['progress']} (进行中{info['in_progress']}章)")

    return "\n".join(lines)
