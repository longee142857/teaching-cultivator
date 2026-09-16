# -*- coding: utf-8 -*-
"""Tutor / DSH session list shows every thread, not a 3-item LRU cap."""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHELL = os.path.join(ROOT, "web", "static", "teaching-shell.html")
HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")


def list_tutor_sessions(recents, threads, today, backlog=None, context_id=None):
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
    if context_id:
        add(context_id)
    for it in today or []:
        add(it.get("id"))
    for it in backlog or []:
        add(it.get("id"))
    return out


def is_general_thread_id(sid) -> bool:
    s = "" if sid is None else str(sid)
    return (not s) or s == "general" or bool(re.match(r"^general-\d+$", s))


def start_blank_tutor(state, now_ms=1700000000000):
    """Mirror teaching-shell.html startBlankTutor (mint general-<ts> unless current empty general)."""
    threads = state.setdefault("threads", {})
    recents = state.setdefault("recents", [])
    cur = state.get("contextItemId")
    empty_current = is_general_thread_id(cur) and not threads.get(cur or "general")
    if not empty_current:
        nid = "general-%s" % now_ms
        threads[nid] = []
        state["contextItemId"] = nid
    elif not cur:
        state["contextItemId"] = "general"
        threads.setdefault("general", [])
    recents[:] = [r for r in recents if r.get("id") != state["contextItemId"]]
    recents.insert(0, {"id": state["contextItemId"], "title": "新对话", "subject": ""})
    return state


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
    check("backlogItems().forEach" in html and "listTutorSessions" in html, "union unanswered backlog")
    check("function isGeneralThreadId" in html, "isGeneralThreadId helper")
    check("function newGeneralThreadId" in html, "newGeneralThreadId helper")
    check('return "general-" + Date.now()' in html, "new thread id is general-<timestamp>")
    check("function startBlankTutor" in html, "startBlankTutor helper")
    check("新建对话" in html, "新建对话 control present")
    check("data-od-id=\"btn-new-tutor\"" in html, "desktop header 新建对话")
    check("data-od-id=\"tchip-new\"" in html, "mobile strip 新建对话")
    check("data-od-id=\"btn-new-tutor-rail\"" in html, "desktop recents 新建对话")
    check("空白聊天" not in html, "replaced 空白聊天 with 新建对话")
    check("threadId: tid" in html, "sendChat passes actual thread id")
    check('threadId: blank ? "general" : tid' not in html, "sendChat does not collapse to general")
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

    backlog = [{"id": "i99", "title": "昨日未答", "backlog": True}]
    ids_bl = list_tutor_sessions(recents, threads, today, backlog=backlog)
    check("i99" in ids_bl, "unanswered backlog enters session list")
    check(ids_bl[-1] == "i99", f"backlog appended after today, got {ids_bl}")

    item_thread = {"i12": [{"role": "user", "text": "这题怎么做"}]}
    stale_general = {"general": [{"role": "user", "text": "旧通用对话"}]}
    state = {
        "contextItemId": "i12",
        "threads": dict(item_thread, **stale_general),
        "recents": [{"id": "i12", "title": "高等数学 · 夹逼"}],
    }
    start_blank_tutor(state, now_ms=1700000000123)
    nid = state["contextItemId"]
    check(nid == "general-1700000000123", f"minted general-<ts>, got {nid}")
    check(state["threads"][nid] == [], "new thread empty")
    check(state["threads"]["general"] == stale_general["general"], "legacy general intact")
    check(state["threads"]["i12"] == item_thread["i12"], "item-bound thread intact")
    check(any(r["id"] == nid for r in state["recents"]), "new general listed in recents")
    # switching back
    state["contextItemId"] = "i12"
    check(state["threads"]["i12"][0]["text"] == "这题怎么做", "switch back keeps item messages")
    state["contextItemId"] = "general"
    check(len(state["threads"]["general"]) == 1, "switch back to old general")
    start_blank_tutor(state, now_ms=1700000000999)
    check(state["contextItemId"] == "general-1700000000999", "second 新建对话 mints another id")
    check("general-1700000000123" in state["threads"], "prior new general remains")

    empty = {"contextItemId": "general", "threads": {"general": []}, "recents": []}
    start_blank_tutor(empty, now_ms=1)
    check(empty["contextItemId"] == "general", "reuse empty current general instead of stacking blanks")

    check(is_general_thread_id("general"), "legacy general is general")
    check(is_general_thread_id("general-1700000000123"), "timestamped general is general")
    check(not is_general_thread_id("i12"), "item id is not general")

    check("include_backlog" in host, "DSH list_today_questions advertises include_backlog")
    check("function isGeneralThreadId" in host, "DSH host treats general-* as blank threads")
    check("新建对话" in open(os.path.join(ROOT, "integrations", "dsh-mentor-team", "client.js"), encoding="utf-8").read(),
          "DSH client 新建对话")
    lect = re.search(r"id:\s*'lecturer'.*?tools:\s*\[([^\]]*)\]", host, re.S)
    check(lect is not None and "adjust_difficulty" not in lect.group(1), "lecturer stays read-only")

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
    btn = re.search(r"\.recent-btn\s*\{[^}]*min-width:\s*0[^}]*\}", html)
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
