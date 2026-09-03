# -*- coding: utf-8 -*-
"""HTML/CSS hooks: mobile Capability Brain 脑图 is reachable (no visual runner).

CK @ ~390px: open /capability-brain.html and practice embed (?embed=1&tab=events),
confirm 脑图 tab under the topbar, stage visible, 左视/右视/顶视/斜视 usable.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HTML = os.path.join(ROOT, "web", "static", "capability-brain.html")
CSS = os.path.join(ROOT, "web", "static", "assets", "cap-style.css")
JS = os.path.join(ROOT, "web", "static", "assets", "cap-app.js")
SHELL = os.path.join(ROOT, "web", "static", "teaching-shell.html")


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    html = open(HTML, encoding="utf-8").read()
    css = open(CSS, encoding="utf-8").read()
    js = open(JS, encoding="utf-8").read()
    shell = open(SHELL, encoding="utf-8").read()

    check('data-tab="events"' in html, "events tab exists")
    check(">脑图<" in html or ">脑图 " in html, "tab labelled 脑图")
    check('data-tab="mastery"' in html, "mastery tab kept")
    check('id="event-stage"' in html and 'id="brain-plate"' in html, "brain stage markup present")
    check("左视" in html and "右视" in html and "顶视" in html and "斜视" in html, "view presets kept")
    check('data-open-tab="events"' in html, "mastery fold opens 脑图")
    check("需切到「事件目录（占位）」" not in html, "dead hint removed")

    check(".view-tabs{ order: 3" not in css.replace(" ", ""), "view-tabs not ordered after stage")
    check(not re.search(r"\.view-tabs\s*\{[^}]*order\s*:\s*3", css), "no view-tabs order:3")
    check("#event-stage{ position:relative; flex:1 1 auto; min-height:0; height:100%; }" in css.replace("\n", " ").replace("  ", " ")
          or ("#event-stage{" in css and "min-height:0" in css),
          "event-stage has min-height:0 (not 100% of auto parent)")
    check("html.is-embedded #app{ height:100%; min-height:0; }" in css, "embed #app fills iframe")
    check("#app{" in css and "height:100%" in css, "#app fills viewport")

    check("function defaultTab" in js, "defaultTab helper")
    check("q.get('embed') === '1'" in js, "embed defaults to events tab")
    check("data-open-tab" in js, "bind open-tab buttons")
    check("max-width: 820px" in js, "narrow viewport defaults to 脑图")

    check("embed=1&tab=events" in shell, "practice embed loads 脑图 tab")
    check(".brain-host iframe" in shell and "height: 100%" in shell, "iframe fills brain-host")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
