# -*- coding: utf-8 -*-
"""双周卷 due 边界测试：按日历日比较，08:00 槽位不被 last_run 分钟偏移卡住。

场景（mg#6）：last_run=2026-07-26 08:23，槽位 08:00。8/9（周日）08:00 应到期。
旧逻辑精确时刻比较 → 差 23 分钟未满 14 天 → 推到 8/16。
新逻辑按日历日 → 7/26 到 8/9 是 14 个日历日 → 8/9 当天到期。
"""
from __future__ import annotations

import sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.biweekly_exam import biweekly_is_due, next_biweekly_slot, save_state, load_state

fails = 0

def check(cond, msg):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        fails += 1

def main():
    # 构造：last_run = 7/26 08:23（带分钟偏移）
    save_state({
        "last_run": "2026-07-26T08:23:36.444938",
        "last_paper_ids": ["2026-07-26_math", "2026-07-26_comm"],
    })

    # 场景1：8/9（周日）08:00 应到期
    t = datetime(2026, 8, 9, 8, 0, 0)
    check(biweekly_is_due(t), "8/9 08:00 应到期（日历日差=14）")

    # 场景2：8/8（周六）08:00 未到期（差 13 天）
    t2 = datetime(2026, 8, 8, 8, 0, 0)
    check(not biweekly_is_due(t2), "8/8 08:00 未到期（差 13 天）")

    # 场景3：8/9 08:00 的 next slot 应是 8/9 08:00 本身（当天到期）
    slot = next_biweekly_slot(t)
    check(slot.date() == datetime(2026, 8, 9).date(),
          f"8/9 到期时 next slot 应命中当天 ({slot.isoformat()})")

    # 场景4：8/2（周日，差 7 天）next slot 应跳到 8/9
    t4 = datetime(2026, 8, 2, 8, 0, 0)
    slot4 = next_biweekly_slot(t4)
    check(slot4.date() == datetime(2026, 8, 9).date(),
          f"8/2 检查时 next slot 应跳到 8/9 ({slot4.isoformat()})")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL BIWEEKLY DUE TESTS PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
