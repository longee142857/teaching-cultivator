# -*- coding: utf-8 -*-
"""同日补触发：08:00 长任务压过 09:00 时，当日 math 日推不得滚到明天。

纯 datetime / scheduler，无钉钉、无 live 推送。
"""
from __future__ import annotations

import datetime
import os
import sys
import time
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.modules.setdefault("dingtalk_stream", MagicMock())

from main import (  # noqa: E402
    PUSH_SLOTS,
    _cultivate_consumed_key,
    _daily_slot_target,
    _day_for_slot,
    _merge_today_pushes_into_consumed,
    _next_scheduled_event,
    _note_event_fired,
    _start_biweekly_worker,
)


fails = 0


def check(cond, msg):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        fails += 1


def _future_biweekly(now):
    """测试里把双周槽钉到更远的周日，避免读盘 state 干扰日推排序。"""
    return now.replace(hour=8, minute=0, second=0, microsecond=0) + datetime.timedelta(days=14)


def _simulate_until(
    start,
    end,
    *,
    job_seconds,
    job_kinds=("github_push", "biweekly_exam"),
    today_pushes=None,
):
    """模拟 scheduler wait/fire 循环（含 30s 尾间隔）。job_seconds=长任务占用。"""
    now = start
    consumed: set = set()
    fired: list[tuple[datetime.datetime, str, str | None]] = []
    skipped: list[tuple[datetime.datetime, str, str | None]] = []
    steps = 0
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        while now < end and steps < 400:
            steps += 1
            target, kind, payload = _next_scheduled_event(
                now, consumed=consumed, today_pushes=today_pushes,
            )
            wait = (target - now).total_seconds()
            if wait >= 120:
                now += datetime.timedelta(seconds=30)
                continue
            if wait > 0:
                now += datetime.timedelta(seconds=wait)
            if kind == "cultivate" and payload:
                _merge_today_pushes_into_consumed(consumed, now, today_pushes)
                if _cultivate_consumed_key(payload, _day_for_slot(now)) in consumed:
                    skipped.append((now, kind, payload))
                    now += datetime.timedelta(seconds=30)
                    continue
            fired.append((now, kind, payload))
            _note_event_fired(consumed, kind, payload, now)
            work = job_seconds if kind in job_kinds else 1
            now += datetime.timedelta(seconds=work + 30)
    return fired, skipped


def main():
    sun = datetime.datetime(2026, 8, 30, 0, 0, 0)  # Sunday
    check(sun.weekday() == 6, "2026-08-30 is Sunday")

    # ── 1. 过点同日：09:00 保持当天，不 +1 天 ──
    now = sun.replace(hour=10, minute=0)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        target, kind, payload = _next_scheduled_event(now)
    check(kind == "cultivate" and payload == "math",
          f"10:00 Sunday next is cultivate/math (got {kind}/{payload})")
    check(target.date() == now.date() and target.hour == 9,
          f"overdue math stays Sunday 09:00, not +1 day (got {target.isoformat()})")

    old_roll = now.replace(hour=9, minute=0) + datetime.timedelta(days=1)
    check(target.date() != old_roll.date(),
          "must not silently roll 09:00 math to Monday")

    # ── 2. 已消费则滚到明天，避免同槽连发 ──
    consumed = set()
    _note_event_fired(consumed, "cultivate", "math", now)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t2, k2, p2 = _next_scheduled_event(now, consumed=consumed)
    math_again_today = (
        k2 == "cultivate" and p2 == "math" and t2.date() == now.date()
    )
    check(not math_again_today,
          f"consumed Sunday math must not refire today (got {k2}/{p2} {t2})")

    # ── 3. 长任务从 08:00 压过 09:00：当日 math 仍会 fire ──
    fired, _skipped = _simulate_until(
        sun.replace(hour=7, minute=50),
        sun.replace(hour=12, minute=0),
        job_seconds=2 * 3600,
    )
    kinds = [(t, k, p) for t, k, p in fired]
    math_fires = [t for t, k, p in fired if k == "cultivate" and p == "math"]
    check(len(math_fires) == 1, f"math cultivate fires once (got {len(math_fires)}; events={kinds})")
    if math_fires:
        check(math_fires[0].date() == sun.date(),
              f"math runs Sunday after 2h 08:00 job, not +1 day (got {math_fires[0].isoformat()})")
        check(math_fires[0] >= sun.replace(hour=10),
              f"math catch-up is after the long job (got {math_fires[0].isoformat()})")

    monday_math = [t for t in math_fires if t.date() == (sun + datetime.timedelta(days=1)).date()]
    check(not monday_math, "math must not be deferred to Monday")

    # ── 4. 15:00 / 19:00 同样同日补，不丢到明天 ──
    late = sun.replace(hour=20, minute=10)
    consumed_late = set()
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_m, k_m, p_m = _next_scheduled_event(late, consumed=consumed_late)
    check((k_m, p_m) == ("cultivate", "math") and t_m.date() == sun.date(),
          f"20:10 still owes Sunday math first (got {k_m}/{p_m} {t_m})")
    _note_event_fired(consumed_late, "cultivate", "math", late)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_c, k_c, p_c = _next_scheduled_event(late, consumed=consumed_late)
    check((k_c, p_c) == ("cultivate", "comm") and t_c.date() == sun.date(),
          f"then Sunday 15:00 comm (got {k_c}/{p_c} {t_c})")
    _note_event_fired(consumed_late, "cultivate", "comm", late)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_r, k_r, p_r = _next_scheduled_event(late, consumed=consumed_late)
    check((k_r, p_r) == ("cultivate", "review") and t_r.date() == sun.date(),
          f"then Sunday 19:00 review (got {k_r}/{p_r} {t_r})")

    # ── 5. 其它槽位仍按原规则滚动（github / judge / weekly 不被这次改坏）──
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        # 已消费当日三槽后，10:00 应走向 11:00 pregen，而不是再发 math
        all_done = set()
        for _, subj in PUSH_SLOTS:
            _note_event_fired(all_done, "cultivate", subj, now)
        t_n, k_n, p_n = _next_scheduled_event(now, consumed=all_done)
    check(k_n == "pregen" and t_n.date() == sun.date() and t_n.hour == 11,
          f"after daily pushes, next is Sunday 11:00 pregen (got {k_n}/{p_n} {t_n})")

    mon_morning = datetime.datetime(2026, 8, 31, 7, 0, 0)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_gh, k_gh, _ = _next_scheduled_event(mon_morning)
    check(k_gh == "github_push" and t_gh == mon_morning.replace(hour=8, minute=0),
          f"Monday 07:00 still schedules github 08:00 (got {k_gh} {t_gh})")

    sun_1930 = sun.replace(hour=19, minute=30)
    consumed_eve = set()
    for _, subj in PUSH_SLOTS:
        _note_event_fired(consumed_eve, "cultivate", subj, sun_1930)
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_w, k_w, _ = _next_scheduled_event(sun_1930, consumed=consumed_eve)
    check(k_w == "weekly_report" and t_w == sun.replace(hour=20, minute=0),
          f"Sunday 19:30 still schedules weekly 20:00 (got {k_w} {t_w})")

    # ── 6. 组卷工作线程不堵住调用方 ──
    started = []
    finished = []

    class _Bot:
        def push_biweekly_exams(self):
            started.append(time.monotonic())
            time.sleep(0.35)
            finished.append(time.monotonic())

    t0 = time.monotonic()
    _start_biweekly_worker(_Bot())
    elapsed = time.monotonic() - t0
    check(elapsed < 0.15, f"biweekly worker returns immediately ({elapsed:.3f}s)")
    deadline = time.monotonic() + 1.0
    while not finished and time.monotonic() < deadline:
        time.sleep(0.02)
    check(bool(started) and bool(finished), "biweekly worker still runs the job")

    # _daily_slot_target 直接断言旧 +1 天 vs 同日补
    slot = _daily_slot_target(
        now, "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=True,
    )
    check(slot == now.replace(hour=9, minute=0, second=0, microsecond=0),
          f"_daily_slot_target catch-up keeps Sunday 09:00 (got {slot})")
    slot_old = _daily_slot_target(
        now, "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=False,
    )
    check(slot_old.date() == (sun + datetime.timedelta(days=1)).date(),
          f"without catch-up, slot still +1 day (got {slot_old.date()})")

    # ── 7. 人工补发已落库 → 过点 09:00 不得再发（#5 consumed 洞）──
    now_1016 = sun.replace(hour=10, minute=16)
    manual_math = [{"subject": "math", "slot": "math", "item_id": 127}]
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=_future_biweekly):
        t_dup, k_dup, p_dup = _next_scheduled_event(
            now_1016, consumed=set(), today_pushes=manual_math,
        )
    math_again = (
        k_dup == "cultivate" and p_dup == "math" and t_dup.date() == now_1016.date()
    )
    check(not math_again,
          f"existing Sunday math push suppresses overdue 09:00 (got {k_dup}/{p_dup} {t_dup})")

    fired_dup, skipped_dup = _simulate_until(
        sun.replace(hour=7, minute=50),
        sun.replace(hour=12, minute=0),
        job_seconds=2 * 3600,
        today_pushes=manual_math,
    )
    math_dup = [t for t, k, p in fired_dup if k == "cultivate" and p == "math"]
    check(len(math_dup) == 0,
          f"manual catch-up + scheduler recover must not both send (fired math={math_dup})")
    check(any(k == "github_push" for _, k, _ in fired_dup),
          "github 08:00 still fires when math is already pushed")

    # 真 SQLite list_today_pushes：周日 10:12 已有 math → 10:16 不补发
    import tempfile
    import config as config_mod
    from learner import db as db_mod
    from learner.db import get_store, reset_store, utc_from_shanghai

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "teaching.db")
        with patch.object(config_mod, "DATA_DIR", td), \
             patch.object(config_mod, "TEACHING_DB", db_path):
            reset_store()
            try:
                store = get_store(db_path)
                iid = store.insert_bank_item(
                    subject="math",
                    question="manual catch-up bank #127",
                    answer="1",
                    status="ready",
                )
                store.record_push_for_item(
                    item_id=iid,
                    learner_id=None,
                    slot="math",
                    pushed_at=utc_from_shanghai("2026-08-30", "10:12"),
                )
                rows = store.list_today_pushes(None, "2026-08-30")
                check(any((r.get("subject") or "").lower() == "math" for r in rows),
                      f"list_today_pushes has Sunday math (n={len(rows)})")
                with patch("learner.biweekly_exam.next_biweekly_slot",
                           side_effect=_future_biweekly):
                    t_db, k_db, p_db = _next_scheduled_event(
                        now_1016, consumed=set(), today_pushes=rows,
                    )
                db_math = (
                    k_db == "cultivate" and p_db == "math"
                    and t_db.date() == now_1016.date()
                )
                check(not db_math,
                      f"SQLite Sunday math push blocks 09:00 catch-up (got {k_db}/{p_db} {t_db})")
            finally:
                reset_store()

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL SCHEDULER SAME-DAY TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
