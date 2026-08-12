# -*- coding: utf-8 -*-
"""pi_active_learner 绑定（多学员 X-Learner-Id）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def main() -> int:
    from agent.pi_rpc_bridge import bind_active_learner

    with tempfile.TemporaryDirectory() as td:
        with patch("config.DATA_DIR", td):
            path = bind_active_learner("04022300566420984205")
            check(path.is_file(), "writes pi_active_learner.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            check(data.get("learner_id") == "04022300566420984205", "learner_id raw staff")
            check(data.get("safe_id") == "04022300566420984205", "safe_id")
            bind_active_learner("other_staff_99")
            data2 = json.loads(Path(td, "pi_active_learner.json").read_text(encoding="utf-8"))
            check(data2.get("learner_id") == "other_staff_99", "overwrite on next ask")
    print("=" * 40)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL LEARNER BIND TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
