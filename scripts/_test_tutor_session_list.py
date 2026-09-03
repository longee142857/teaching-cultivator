# -*- coding: utf-8 -*-
"""Tutor / DSH session list shows every thread, not a 3-item LRU cap."""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHELL = os.path.join(ROOT, "web", "static", "teaching-shell.html")
HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")


def list_tutor_sessions(recents, threads, today):
    """Mirror teaching-shell.html listTutorSessions merge order."""
    seen = set()
    out = []

    def add(sid):
        if not sid or sid in seen:
            return
        seen.add(sid)
        out.append(sid)

    for r in recents or []:
        add(r.get("id"))
    for key in threads or {}:
        add(key)
    for it in today or []:
        add(it.get("id"))
    return out


def preview_text(raw: str) -> str:
    """Mirror teaching-shell.html previewText (strip newlines + LaTeX markers)."""
    s = "" if raw is None else str(raw)
    s = re.sub(r"\$\$[\s\S]*?\$\$", " ", s)
    s = re.sub(r"\\\[[\s\S]*?\\\]", " ", s)
    s = re.sub(r"\\\([\s\S]*?\\\)", " ", s)
    s = re.sub(r"\$[^$\n]+\$", " ", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = re.sub(r"[{}]", " ", s)
    s = re.sub(r"[\r\n]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    html = open(SHELL, encoding="utf-8").read()
    host = open(HOST, encoding="utf-8").read()

    check("function listTutorSessions" in html, "listTutorSessions helper")
    check("Object.keys(state.threads" in html, "union thread keys")
    check("todayItems().forEach" in html and "listTutorSessions" in html, "union today items")
    check("state.recents = state.recents.slice(0, 3)" not in html, "bumpRecent no longer caps at 3")
    check("(state.recents || []).slice(0, 3)" not in html, "renderRecents no longer slices 3")
    check("(state.recents || []).slice(0, 6)" not in html, "tutor strip no longer slices 6")
    check("listTutorSessions()" in html, "renderers use full session list")
    check("overflow-y: auto" in html, "desktop recents list can scroll")

    recents = [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]
    threads = {f"i{n}": [{"role": "user", "text": "x"}] for n in range(1, 6)}
    today = [{"id": "i6", "title": "今日未聊"}]
    ids = list_tutor_sessions(recents, threads, today)
    check(ids == ["i1", "i2", "i3", "i4", "i5", "i6"], f"all ids listed, got {ids}")
    check(len(ids) > 3, ">3 sessions visible")

    # Do not treat DSH T1 40 msgs/thread as this bug
    check("if (arr.length > 40) arr.splice(0, arr.length - 40)" in host, "host T1 40 msgs/thread left in place")
    bump = re.search(r"function bumpRecent\([\s\S]*?\n      \}", html)
    check(bump is not None and "slice(0, 3)" not in bump.group(0), "bumpRecent body has no slice(0, 3)")

    check("function previewText" in html, "preview sanitizer")
    check("previewText(msgs[msgs.length - 1].text)" in html, "sidebar uses sanitizer not raw slice")
    check("last.slice(0, 28)" not in html, "no raw 28-char last-message slice")
    prev = re.search(r"\.recent-preview\s*\{[^}]+\}", html)
    check(
        prev is not None
        and "-webkit-line-clamp: 2" in prev.group(0)
        and "min-width: 0" in prev.group(0)
        and "overflow: hidden" in prev.group(0)
        and "text-overflow: ellipsis" in prev.group(0)
        and "display: -webkit-box" in prev.group(0)
        and "-webkit-box-orient: vertical" in prev.group(0),
        "recent-preview two-line clamp + min-width:0",
    )
    btn = re.search(r"\.recent-btn\s*\{[^}]+\}", html)
    check(btn is not None and "min-width: 0" in btn.group(0), "recent-btn min-width:0")
    chip = re.search(r"\.tutor-chip \.tc-title,\s*\n\s*\.tutor-chip \.tc-sub\s*\{[^}]+\}", html)
    check(
        chip is not None and "-webkit-line-clamp: 2" in chip.group(0) and "min-width: 0" in chip.group(0),
        "mobile chip title/sub two-line clamp",
    )

    latex = "看这步\n$$\\frac{1}{2}x$$\n再算 $e^{i\\pi}$ 即可"
    cleaned = preview_text(latex)
    check("\n" not in cleaned, "newlines stripped")
    check("\\frac" not in cleaned and "$$" not in cleaned and "$" not in cleaned,
          f"latex markers stripped, got {cleaned!r}")
    check("看这步" in cleaned and "再算" in cleaned, f"prose kept {cleaned!r}")
    check(preview_text("$$\\frac{a}{b}$$") == "", "pure formula becomes empty (UI fallback 公式)")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
