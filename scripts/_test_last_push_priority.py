# -*- coding: utf-8 -*-
"""_load_last_push_record 修复测试：定时公共推送后，批改应读最新的 last_class 而非旧个人题。

场景：个人 last_push(旧题) + 公共 last_class(新题) 同时存在，应取 timestamp 新的。
"""
from __future__ import annotations

import json
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

    with tempfile.TemporaryDirectory() as td:
        os.environ["TEACHING_DATA_DIR"] = td
        cfg.DATA_DIR = td

        from learner import paths as P
        personal = P.last_push_path()
        public = P.public_last_class_path()
        os.makedirs(os.path.dirname(personal), exist_ok=True)
        os.makedirs(os.path.dirname(public), exist_ok=True)

        now = datetime.now(timezone.utc)

        # 个人 last_push：旧题（昨天）
        with open(personal, "w", encoding="utf-8") as f:
            json.dump({
                "subject": "comm", "kp": "卷积码与维特比译码",
                "question": "旧的维特比题...",
                "timestamp": (now - timedelta(days=1)).isoformat(),
            }, f, ensure_ascii=False)

        # 公共 last_class：新题（今天 19:01）
        with open(public, "w", encoding="utf-8") as f:
            json.dump({
                "subject": "review", "kp": "二重积分与三重积分",
                "question": "新的二重积分题...",
                "timestamp": (now - timedelta(hours=1)).isoformat(),
            }, f, ensure_ascii=False)

        rec = T._load_last_push_record()
        check(rec.get("kp") == "二重积分与三重积分",
              f"应选新的公共 last_class (kp={rec.get('kp')})")

        q = T._load_last_push_question()
        check(q.startswith("新的二重积分题"), f"question 应为新题: {q[:20]}")

    # 反向：个人更新 → 应选个人
    with tempfile.TemporaryDirectory() as td:
        os.environ["TEACHING_DATA_DIR"] = td
        cfg.DATA_DIR = td
        from learner import paths as P2
        personal = P2.last_push_path()
        public = P2.public_last_class_path()
        os.makedirs(os.path.dirname(personal), exist_ok=True)
        os.makedirs(os.path.dirname(public), exist_ok=True)

        now = datetime.now(timezone.utc)
        with open(personal, "w", encoding="utf-8") as f:
            json.dump({
                "subject": "math", "kp": "私聊自出题",
                "question": "刚私聊出的题...",
                "timestamp": now.isoformat(),
            }, f, ensure_ascii=False)
        with open(public, "w", encoding="utf-8") as f:
            json.dump({
                "subject": "comm", "kp": "旧公共题",
                "question": "旧的公共题...",
                "timestamp": (now - timedelta(days=2)).isoformat(),
            }, f, ensure_ascii=False)

        rec = T._load_last_push_record()
        check(rec.get("kp") == "私聊自出题",
              f"私聊更新时应选个人 (kp={rec.get('kp')})")


if __name__ == "__main__":
    main()
