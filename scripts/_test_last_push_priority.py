# -*- coding: utf-8 -*-
"""_load_last_push_record 修复测试：定时公共推送后，批改应读最新的公共题而非旧个人题。

BIG-TEACH-013：权威源为 SQLite pushes（公共 learner_id IS NULL ∪ 个人）。
场景：个人旧题 + 公共新题 同时存在，应取 pushed_at 最新的。
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.context import bind_learner


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    with bind_learner("test_last_push_prio"):
        _run(check)

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL LAST_PUSH PRIORITY TESTS PASSED")
    sys.exit(0)


def _run(check):
    import config as cfg
    import agent.tools as T
    from learner.db import get_store, reset_store

    now = datetime.now(timezone.utc)

    # 场景 1：个人旧题（昨天） + 公共新题（1 小时前）→ 应选公共新题
    with tempfile.TemporaryDirectory() as td:
        cfg.DATA_DIR = td
        reset_store()
        store = get_store()
        store.record_push(
            subject="comm", question="旧的维特比题...", kp="卷积码与维特比译码",
            learner_id="test_last_push_prio",
            pushed_at=(now - timedelta(days=1)).isoformat(),
        )
        store.record_push(
            subject="review", question="新的二重积分题...", kp="二重积分与三重积分",
            learner_id=None,
            pushed_at=(now - timedelta(hours=1)).isoformat(),
        )

        rec = T._load_last_push_record()
        check(rec.get("kp") == "二重积分与三重积分",
              f"应选新的公共 last_class (kp={rec.get('kp')})")

        q = T._load_last_push_question()
        check(q.startswith("新的二重积分题"), f"question 应为新题: {q[:20]}")

    # 场景 2：个人新题（now） + 公共旧题（2 天前）→ 应选个人
    with tempfile.TemporaryDirectory() as td:
        cfg.DATA_DIR = td
        reset_store()
        store = get_store()
        store.record_push(
            subject="math", question="刚私聊出的题...", kp="私聊自出题",
            learner_id="test_last_push_prio",
            pushed_at=now.isoformat(),
        )
        store.record_push(
            subject="comm", question="旧的公共题...", kp="旧公共题",
            learner_id=None,
            pushed_at=(now - timedelta(days=2)).isoformat(),
        )

        rec = T._load_last_push_record()
        check(rec.get("kp") == "私聊自出题",
              f"私聊更新时应选个人 (kp={rec.get('kp')})")


if __name__ == "__main__":
    main()
