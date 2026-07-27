# -*- coding: utf-8 -*-
"""BIG-TEACH-012a Wave A correctness: #4 deliver gate, #5 adjust_difficulty, #6 bkt import."""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def sep(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    # ── #4 deliver False → no record / last_push ──
    sep("1. #4 deliver False skips record/last_push")
    import cultivate as cultivate_mod
    from intervention import InterventionDecision

    decision = InterventionDecision(
        "practice",
        "basic",
        "极限:test",
        3,
    )
    with patch.object(cultivate_mod, "_bkt_available", True), \
         patch.object(cultivate_mod, "assess_state", return_value={"bkt_log": MagicMock()}), \
         patch.object(cultivate_mod, "decide", return_value=decision), \
         patch.object(cultivate_mod, "generate", return_value="Q body"), \
         patch.object(cultivate_mod, "deliver", return_value=False) as mock_deliver, \
         patch.object(cultivate_mod, "record") as mock_record, \
         patch.object(cultivate_mod, "_save_last_push") as mock_save:
        cultivate_mod._last_answer = "A"
        cultivate_mod._last_ref_source = ""
        cultivate_mod.cultivate("math")
        check(mock_deliver.called, "deliver called")
        check(not mock_record.called, "record NOT called")
        check(not mock_save.called, "last_push NOT saved")

    with patch.object(cultivate_mod, "_bkt_available", True), \
         patch.object(cultivate_mod, "assess_state", return_value={"bkt_log": MagicMock()}), \
         patch.object(cultivate_mod, "decide", return_value=decision), \
         patch.object(cultivate_mod, "generate", return_value="Q body"), \
         patch.object(cultivate_mod, "deliver", return_value=True), \
         patch.object(cultivate_mod, "record") as mock_record, \
         patch.object(cultivate_mod, "_save_last_push") as mock_save:
        cultivate_mod._last_answer = "A"
        cultivate_mod._last_ref_source = ""
        cultivate_mod.cultivate("math")
        check(mock_record.called, "record called on deliver ok")
        check(mock_save.called, "last_push saved on deliver ok")

    # ── #5 adjust_difficulty no mastery bkt.record ──
    sep("2. #5 adjust_difficulty does not call bkt.record")
    from agent import tools as tools_mod
    import config as config_mod
    import json

    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td), \
             patch("cultivate.set_difficulty_pref", return_value=True), \
             patch.object(
                 tools_mod,
                 "_read_latest_entry",
                 return_value={"kp": "极限", "raw": "决策原因：极限:x"},
             ), \
             patch("bkt.BKTLogger.record") as mock_rec:
            msg = tools_mod.adjust_difficulty("math", "basic")
            check("已调整" in msg or "难度" in msg, f"msg={msg[:80]}")
            check(not mock_rec.called, "bkt.record NOT called")
            log = os.path.join(td, "answer-log.jsonl")
            check(os.path.exists(log), "audit log written to temp DATA_DIR")
            row = json.loads(open(log, encoding="utf-8").readline())
            check(row.get("status") == "audit", f"audit status={row.get('status')}")
            check(row.get("update_applied") is False, "audit not applied")
            check(row.get("correct") is None, "audit correct is None")

    # ── #6 bkt import without KB_PATH ──
    sep("3. #6 relative monorepo lib on path")
    import config as config_mod

    rel = os.path.normpath(os.path.join(ROOT, "../knowledge-system/lib"))
    check(os.path.isdir(rel), f"rel lib exists: {rel}")
    # config already ran at import; ensure path was inserted or is importable
    try:
        import bkt  # noqa: F401
        check(True, "import bkt ok")
    except ImportError as e:
        check(False, f"import bkt failed: {e}")

    # simulate empty KB_PATH still resolves via relative fallback logic
    kb_env = os.environ.get("KB_PATH")
    try:
        if "KB_PATH" in os.environ:
            del os.environ["KB_PATH"]
        # re-run the fallback snippet equivalent
        _rel_lib = os.path.normpath(
            os.path.join(os.path.dirname(config_mod.__file__), "../knowledge-system/lib")
        )
        check(os.path.isdir(_rel_lib), f"config relative fallback path exists: {_rel_lib}")
    finally:
        if kb_env is not None:
            os.environ["KB_PATH"] = kb_env

    # override_grade tool registered on Agent
    sep("4. override_grade wired in agent")
    from agent.agent import TeachingAgent

    schemas = TeachingAgent(bot=None)._build_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    check("override_grade" in names, "override_grade in tool schemas")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL WAVE A CORRECTNESS TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
