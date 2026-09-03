# -*- coding: utf-8 -*-
"""DSH restore: assistant can adjust_difficulty; lecturer cannot; persist via old tool."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")


def _roster_tools(js: str, role_id: str) -> str:
    m = re.search(
        r"id:\s*'%s'.*?tools:\s*\[([^\]]*)\]" % re.escape(role_id),
        js,
        re.S,
    )
    return m.group(1) if m else ""


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    js = open(HOST, encoding="utf-8").read()
    asst = _roster_tools(js, "assistant")
    lect = _roster_tools(js, "lecturer")
    check("adjust_difficulty" in asst, "assistant roster includes adjust_difficulty")
    check("adjust_difficulty" not in lect, "lecturer roster excludes adjust_difficulty")
    check("WRITE_TOOLS" in js and "adjust_difficulty: true" in js, "write-tool map")
    check("method: 'POST'" in js and "/v1/tools/" in js, "exec POSTs /v1/tools/{name}")
    check("allowed.indexOf(name) < 0" in js, "role gate on execTool")
    check("__adjustDifficulty" in js, "compose difficulty path")
    check("isDifficultyAsk" in js, "difficulty-ask helper")
    check("不批改、不出题" in js, "grade/generate still gated")
    check("可调用 adjust_difficulty" in js, "assistant prompt may adjust difficulty")
    check("不改难度" in js, "lecturer prompt stays read-only on difficulty")
    # 出题 gate must not swallow 太难
    gate = re.search(r"if \(/批改[\s\S]*?__ruleOnly", js)
    adj = js.find("isDifficultyAsk(msg)")
    check(adj >= 0 and (not gate or adj < gate.start()), "difficulty ask is classified before grade/generate gate")

    from deliver.system_api import WHITELIST, _READ_TOOLS

    check("adjust_difficulty" in WHITELIST, "system_api whitelist has adjust_difficulty")
    check("adjust_difficulty" not in _READ_TOOLS, "adjust_difficulty is POST-only")

    import config as config_mod
    import cultivate as cultivate_mod
    from agent import tools as tools_mod
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td):
            with bind_learner("dsh_diff_u"):
                ok = cultivate_mod.set_difficulty_pref("math", "challenge")
                check(ok is True, "set_difficulty_pref returns True")
                check(cultivate_mod.get_difficulty_pref("math") == "challenge", "pref persisted math=challenge")
                msg = tools_mod.adjust_difficulty("math", "basic")
                check("basic" in msg and "math" in msg, f"old tool message={msg[:80]!r}")
                check(cultivate_mod.get_difficulty_pref("math") == "basic", "old tool writes same difficulty.json")
                from learner import paths as P
                path = P.difficulty_path()
                check(os.path.isfile(path), "difficulty.json exists")
                data = json.loads(open(path, encoding="utf-8").read())
                check(data.get("math") == "basic", f"file contents={data}")

            # mocked system_api call_tool → same python function (binds learner itself)
            from deliver.system_api import call_tool

            r = call_tool("adjust_difficulty", "dsh_diff_u", {"subject": "comm", "level": "intermediate"})
            check(r.get("ok") is True, f"call_tool ok={r}")
            with bind_learner("dsh_diff_u"):
                check(cultivate_mod.get_difficulty_pref("comm") == "intermediate", "API wrap hits old tool")
                check(cultivate_mod.get_difficulty_pref("math") == "basic", "math pref kept")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
