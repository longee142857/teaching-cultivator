"""GitHub Trending 消息格式化 — 钉钉 Markdown。"""
from __future__ import annotations

from datetime import date, datetime

LANG_EMOJI = {
    "Python": "🐍", "TypeScript": "🟦", "JavaScript": "🟨",
    "Go": "🔵", "Rust": "🦀", "Java": "☕", "C": "⚙️",
    "C++": "⚙️", "Ruby": "💎", "Kotlin": "🟣", "Swift": "🟠",
    "HTML": "🌐", "CSS": "🎨", "Shell": "🐚", "PowerShell": "🪟",
    "Jupyter Notebook": "📓", "R": "📊", "C#": "#️⃣",
}


def format_trending(repos: list[dict], max_count: int = 10, channel: str = "dingtalk") -> str:
    """repo 列表 → 平台消息文本。

    Args:
        repos: repo dict 列表
        max_count: 最多显示多少个
        channel: 目标渠道（当前只实现 dingtalk）

    Returns:
        格式化后的 Markdown 字符串
    """
    if channel == "dingtalk":
        return _format_dingtalk(repos, max_count)
    return _format_dingtalk(repos, max_count)


def _format_dingtalk(repos: list[dict], max_count: int) -> str:
    """钉钉 Markdown 格式。"""
    today = date.today().isoformat()
    lines = [f"## 🔥 GitHub 热门项目 · {today}\n"]

    if repos:
        lines.append(f"> 共收录 {len(repos)} 个项目，按星标排序。\n")

    for i, r in enumerate(repos[:max_count], 1):
        name = r["name"]
        desc = r["desc"]
        lang = r["lang"]
        stars = r["stars"]
        url = r["url"]
        built = r["built_by"]

        stars_str = f" ⭐ {stars}" if stars else ""
        lang_emoji = LANG_EMOJI.get(lang, "")
        lang_str = f" {lang_emoji} {lang}" if lang else ""

        lines.append(f"**{i}. [{name}]({url})**{stars_str}")
        if desc:
            lines.append(f"   > {desc}")
        meta_parts = [s for s in [lang_str, f"👤 @{', @'.join(built)}" if built else ""] if s]
        if meta_parts:
            lines.append(f"   {'  '.join(meta_parts)}")
        lines.append("")

    return "\n".join(lines)
