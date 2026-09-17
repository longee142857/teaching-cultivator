# -*- coding: utf-8 -*-
"""Lecturer can index today+backlog and show_solution honors item/push."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_kl = os.path.join(ROOT, "knowledge-lib")
if os.path.isdir(_kl) and _kl not in sys.path:
    sys.path.insert(0, _kl)

HOST = os.path.join(ROOT, "integrations", "dsh-mentor-team", "host.js")


def main() -> int:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    js = open(HOST, encoding="utf-8").read()
    lect = re.search(r"id:\s*'lecturer'.*?tools:\s*\[([^\]]*)\]", js, re.S)
    asst = re.search(r"id:\s*'assistant'.*?tools:\s*\[([^\]]*)\]", js, re.S)
    check(lect is not None and "list_today_questions" in lect.group(1),
          "lecturer roster has list_today_questions")
    check(lect is not None and "practice_get_item" in lect.group(1),
          "lecturer roster has practice_get_item")
    check(lect is not None and "show_solution" in lect.group(1),
          "lecturer roster has show_solution")
    check(lect is not None and "adjust_difficulty" not in lect.group(1),
          "lecturer stays read-only (no adjust_difficulty)")
    check(asst is not None and "list_today_questions" in asst.group(1),
          "assistant still has list_today_questions")
    check("args.include_backlog = true" in js, "execTool defaults include_backlog true")
    check("practice_web:show_solution" in js, "show_solution practice item fallback")
    check("backlogItems 是历史未答" in js, "system prompt indexes backlogItems")
    check("show_solution 必须带 item/push" in js, "prompt: show_solution needs item/push")

    import inspect
    from agent.tools import show_solution, list_today_questions

    sig = inspect.signature(show_solution)
    check("item" in sig.parameters and "push" in sig.parameters,
          "show_solution accepts item/push")

    import config as config_mod
    from learner import db as db_mod
    from learner.context import bind_learner
    from learner.db import TZ_SHANGHAI, get_store, reset_store, utc_from_shanghai

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "teaching.db")
        os.environ["TEACHING_DB"] = db_path
        with patch.object(config_mod, "DATA_DIR", td):
            reset_store()
            store = get_store()
            yday = (datetime.now(TZ_SHANGHAI) - timedelta(days=1)).strftime("%Y-%m-%d")
            old_id = store.insert_bank_item(
                subject="math",
                question="积压题UNIQUE_OLD 换元积分",
                answer="√2-1",
                difficulty="basic",
                kp="积压换元",
                solution={
                    "steps": [{"id": "s1", "text": "旧题步骤UNIQUE_OLD_STEP"}],
                    "final_answer": "√2-1",
                },
                status="ready",
            )
            new_id = store.insert_bank_item(
                subject="math",
                question="今日题UNIQUE_NEW 夹逼定理",
                answer="0",
                difficulty="basic",
                kp="夹逼",
                solution={
                    "steps": [{"id": "s1", "text": "新题步骤UNIQUE_NEW_STEP"}],
                    "final_answer": "0",
                },
                status="ready",
            )
            store.record_push_for_item(
                item_id=old_id,
                learner_id="idx_u",
                slot="math",
                pushed_at=utc_from_shanghai(yday, "10:00"),
            )
            store.record_push_for_item(
                item_id=new_id,
                learner_id="idx_u",
                slot="math",
            )
            with bind_learner("idx_u", binding="personal"):
                latest = show_solution()
                check("UNIQUE_NEW" in latest and "UNIQUE_OLD" not in latest,
                      "bare show_solution still latest push")
                by_item = show_solution(item=f"i{old_id}")
                check("UNIQUE_OLD" in by_item and "UNIQUE_OLD_STEP" in by_item,
                      "show_solution(item=backlog) returns old stem/steps")
                check("UNIQUE_NEW" not in by_item,
                      "named backlog show_solution does not leak latest")
                miss = show_solution(item="i999999")
                check(miss.startswith("NO_ENTRY") and "UNIQUE_NEW" not in miss,
                      "missing item is NO_ENTRY, not silent latest")
                today_only = list_today_questions()
                check("UNIQUE_NEW" in today_only or "夹逼" in today_only,
                      "today list has today's push")
                check("历史未答" not in today_only and "积压换元" not in today_only,
                      "tools.py default include_backlog still false")
                with_bl = list_today_questions(include_backlog=True)
                check("历史未答" in with_bl and "积压换元" in with_bl,
                      "include_backlog lists unanswered backlog")
                check(f"i{old_id}" in with_bl, "backlog line exposes public item id")

    return fails


if __name__ == "__main__":
    n = main()
    sys.exit(1 if n else 0)
