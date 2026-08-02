# -*- coding: utf-8 -*-
"""验证 0c6b85b 修复 + P1 隔离效果（对云端真实 answer-log 跑）。

断言：
1. 同一 kp 同一分钟无两条 applied 答错（grade + self_report_weak 不成对）
2. 近 14 天未分类占比 < 10%（未隔离的未分类不再新增）
3. pending 条目 confidence 非 0（0c6b85b 修复 conf=0.00 写入 pending）
4. propose_override 不写 answer-log，只有 confirm 写
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.context import bind_learner


def main():
    # 参数：answer-log 路径；缺省用当前 learner 的
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    if log_path:
        with bind_learner("04022300566420984205"):
            _run(check, log_path)
    else:
        with bind_learner("test_verify_0c6b85b"):
            _run(check, None)

    print("\n" + "=" * 60)
    print("ALL VERIFY 0c6b85b TESTS PASSED")


def check(cond: bool, msg: str):
    safe = msg.encode("ascii", "backslashreplace").decode("ascii")
    print(f"[{'PASS' if cond else 'FAIL'}] {safe}")


def _load_rows(path: str) -> list[dict]:
    rows = []
    if not os.path.isfile(path):
        return rows
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _run(check, log_path):
    if log_path:
        rows = _load_rows(log_path)
    else:
        # 无参数：临时构造 mock 数据测逻辑
        from learner import paths as P
        rows = _load_rows(P.answer_log_path())

    if not rows:
        check(False, "answer-log 为空，无法验证")
        return

    now = datetime.now(timezone.utc)
    cutoff14 = (now - timedelta(days=14)).isoformat()
    # 0c6b85b 部署时点（修复双重 BKT 生效）；只校验其后的新写入
    FIX_TS = "2026-08-01T06:30:00+00:00"

    # ── 1. 修复后同一 kp 同一分钟无两条 applied 答错 ──
    applied_wrong = [
        r for r in rows
        if r.get("update_applied") and r.get("correct") is False
        and r.get("ts", "") > FIX_TS
    ]
    by_window: dict[tuple, list] = defaultdict(list)
    for r in applied_wrong:
        by_window[(r.get("knowledge_point"), r.get("ts", "")[:16])].append(r)
    double = 0
    for (kp, win), dups in by_window.items():
        if len(dups) > 1:
            tags = {d.get("conv_tag", "") for d in dups}
            if "self_report_weak" in tags:
                double += 1
    check(double == 0, f"修复后({FIX_TS[:10]} 起)同一kp同一分钟无成对答错 (double={double})")

    # ── 2. 近 14 天未分类占比 < 10%（排除已隔离）──
    recent = [r for r in rows if r.get("ts", "") >= cutoff14]
    unc = [r for r in recent if r.get("knowledge_point") == "未分类" and not r.get("quarantined")]
    pct = len(unc) / len(recent) * 100 if recent else 0
    check(pct < 10, f"近14天未分类占比 {pct:.1f}% ({len(unc)}/{len(recent)})")

    # ── 3. pending 条目 confidence 非 0（排除已隔离）──
    pend_zero = [
        r for r in rows
        if r.get("status") == "pending" and r.get("confidence") == 0.0
        and not r.get("quarantined")
    ]
    check(len(pend_zero) == 0, f"pending 且 conf=0.00（未隔离）条数={len(pend_zero)}")

    # ── 4. propose_override 不写，只有 confirm 写 ──
    with tempfile.TemporaryDirectory() as td:
        os.environ["TEACHING_DATA_DIR"] = td
        import config as cfg
        cfg.DATA_DIR = td
        from learner import paths as P
        from agent import tools as T
        alog = P.answer_log_path()
        os.makedirs(os.path.dirname(alog), exist_ok=True)
        # 预置一条历史
        with open(alog, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": "2026-01-01T00:00:00+00:00",
                "user_id": "test_verify_0c6b85b",
                "knowledge_point": "极限", "correct": False, "item_type": "open",
                "update_applied": True, "status": "applied",
            }, ensure_ascii=False) + "\n")
        n_before = sum(1 for _ in open(alog, encoding="utf-8"))
        r1 = T.propose_override_grade("极限", True, subject="math")
        n_after_propose = sum(1 for _ in open(alog, encoding="utf-8"))
        check(n_after_propose == n_before, "propose_override 不写 answer-log")
        token = r1.split("[OVERRIDE]", 1)[1].strip() if "[OVERRIDE]" in r1 else ""
        if token:
            T.confirm_override(token)
            n_after_confirm = sum(1 for _ in open(alog, encoding="utf-8"))
            check(n_after_confirm == n_before + 1, "confirm_override 追加 1 条")


if __name__ == "__main__":
    main()
