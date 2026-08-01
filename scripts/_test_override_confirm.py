# -*- coding: utf-8 -*-
"""override 确认卡流程测试：propose → confirm → 覆盖，confirm 前不写 answer-log。

验证点：
1. propose_override 只登记提案，不写 answer-log
2. 同 kp 重复 propose 被去重
3. confirm_override 后真正覆盖（answer-log 追加 overridden 记录）
4. cancel_override 不覆盖
5. note_weak_point 不再记 BKT 假答错
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

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

    with bind_learner("test_override_confirm"):
        _run(check)

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL OVERRIDE CONFIRM TESTS PASSED")
    sys.exit(0)


def _run(check):
    import config as cfg
    import agent.tools as T

    # 临时数据目录
    with tempfile.TemporaryDirectory() as td:
        os.environ["TEACHING_DATA_DIR"] = td
        cfg.DATA_DIR = td

        from learner import paths as P
        alog = P.answer_log_path()
        os.makedirs(os.path.dirname(alog), exist_ok=True)

        # 预置一条"判错"的历史批改
        with open(alog, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": "2026-01-01T00:00:00+00:00",
                "user_id": "test_override_confirm",
                "knowledge_point": "极限",
                "correct": False, "item_type": "open",
                "update_applied": True, "status": "applied",
                "state": {"p_mastery": 0.34, "opportunity_count": 1},
            }, ensure_ascii=False) + "\n")

        # ── 1. propose 不写 answer-log ──
        r1 = T.propose_override_grade("极限", True, subject="math")
        check("登记" in r1, f"propose msg: {r1[:60]}")
        check("[OVERRIDE]" in r1, "propose 带 [OVERRIDE] 标记")
        n_after_propose = sum(1 for _ in open(alog, encoding="utf-8"))
        check(n_after_propose == 1, f"propose 后 answer-log 仍 1 条 (实际 {n_after_propose})")

        # ── 2. 同 kp 重复 propose 去重 ──
        r2 = T.propose_override_grade("极限", True, subject="math")
        check("已有待确认" in r2, f"重复 propose 拦截: {r2[:40]}")

        # ── 3. confirm 后真正覆盖 ──
        token = r1.split("[OVERRIDE]", 1)[1].strip()
        rc = T.confirm_override(token)
        check("已覆盖" in rc, f"confirm msg: {rc[:80]}")
        with open(alog, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        last = lines[-1]
        check(last.get("status") == "overridden", f"overridden status={last.get('status')}")
        check(last.get("correct") is True, f"correct={last.get('correct')}")

        # ── 4. cancel 不覆盖 ──
        before = sum(1 for _ in open(alog, encoding="utf-8"))
        r3 = T.propose_override_grade("傅里叶", False, subject="math")
        ctoken = r3.split("[OVERRIDE]", 1)[1].strip()
        rxc = T.cancel_override(ctoken)
        check("已取消" in rxc, f"cancel msg: {rxc[:40]}")
        n_after_cancel = sum(1 for _ in open(alog, encoding="utf-8"))
        check(n_after_cancel == before, f"cancel 后 answer-log 不变 (实际 {n_after_cancel})")

    # ── 5. note_weak_point 不再记 BKT 假答错 ──
    with tempfile.TemporaryDirectory() as td:
        os.environ["TEACHING_DATA_DIR"] = td
        cfg.DATA_DIR = td
        from learner import paths as P
        import learner.weights_ops as W
        wp = P.weights_path()
        os.makedirs(os.path.dirname(wp), exist_ok=True)
        with open(wp, "w", encoding="utf-8") as f:
            json.dump({"math": {"kp_weights": {"极限": 0.2}}}, f)

        T.note_weak_point("math", "极限", reason="用户自述薄弱")
        alog = P.answer_log_path()
        n_weak = sum(1 for _ in open(alog, encoding="utf-8")) if os.path.exists(alog) else 0
        check(n_weak == 0, f"note_weak 不写 BKT (answer-log {n_weak} 条)")


if __name__ == "__main__":
    main()
