"""报告格式化 — 人可读 + JSON"""
from __future__ import annotations
import json

from learner.model import WeeklyProfile


def format_text(profile: WeeklyProfile, max_len: int = 800) -> str:
    """给用户的简短总结（微信尺寸）。"""
    parts = []
    if profile.summary:
        parts.append(profile.summary[:max_len])
    else:
        parts.append("本周数据还比较少，多练习几轮后分析会更准确。")
    return "\n".join(parts)


def format_detailed(profile: WeeklyProfile) -> str:
    """完整报告（人可读）。"""
    lines = [f"📊 周报 {profile.period_start} ~ {profile.period_end}"]

    if profile.summary:
        lines.extend(["", profile.summary, ""])

    if profile.kp_trends:
        lines.append("📈 掌握度变化")
        for t in profile.kp_trends:
            arrow = "↑" if t.mastery_after > t.mastery_before else "↓" if t.mastery_after < t.mastery_before else "→"
            lines.append(f"  {t.name}: {t.mastery_before:.0%} {arrow} {t.mastery_after:.0%}")
        lines.append("")

    if profile.error_patterns:
        lines.append("🔍 薄弱点")
        for ep in profile.error_patterns:
            lines.append(f"  • {ep.pattern}")
        lines.append("")

    if profile.weak_chains:
        lines.append("🔗 进度瓶颈")
        for c in profile.weak_chains:
            lines.append(f"  • {c['chain']}")

    lines.append(f"\n💬 交互: 推送{profile.engagement.get('total_pushes',0)}次, "
                 f"回复率{profile.engagement.get('reply_rate',0):.0%}")

    lines.append("\n📚 科目进展")
    for subj, info in profile.subjects_progress.items():
        lines.append(f"  {subj}: {info['progress']}")

    return "\n".join(lines)


def format_for_decide(profile: WeeklyProfile) -> str:
    """供 decide() 参考的轻量摘要（紧凑，无格式）。"""
    parts = ["[周报参考]"]
    if profile.error_patterns:
        for ep in profile.error_patterns[:2]:
            parts.append(f"薄弱:{ep.pattern}")
    if profile.weak_chains:
        for c in profile.weak_chains[:1]:
            parts.append(f"瓶颈:{c['chain']}")
    return " | ".join(parts) if len(parts) > 1 else ""
