# -*- coding: utf-8 -*-
"""调度器：工作日同日补触发；周六/周日跳过 09/15/19 日推；双周卷节奏不变。

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

from contextlib import contextmanager

from main import (  # noqa: E402
    PUSH_SLOTS,
    _apply_biweekly_cultivate_skip,
    _biweekly_day_skips_cultivate,
    _cultivate_consumed_key,
    _daily_slot_target,
    _day_for_slot,
    _is_cultivate_skip_day,
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


def _biweekly_at(slot_dt):
    """固定某个周日 08:00；过点后滚 +14 天，避免模拟循环同槽连发。"""
    def _fn(now):
        target = slot_dt
        if target < now:
            return target + datetime.timedelta(days=14)
        return target
    return _fn


@contextmanager
def _sched_patches(*, due=False, last_run="", biweekly_slot=None):
    """默认非双周到期，避免空 last_run 让 biweekly_is_due 恒真、误跳日推。

    biweekly_slot: 覆盖 next_biweekly_slot；默认钉到 +14 天，避免周日 08:00
    组卷槽干扰日推排序。测隔周卷本身时传入「当天 08:00」。
    """
    slot_fn = biweekly_slot if biweekly_slot is not None else _future_biweekly
    with patch("learner.biweekly_exam.next_biweekly_slot", side_effect=slot_fn), \
         patch("learner.biweekly_exam.biweekly_is_due", return_value=due), \
         patch(
             "learner.biweekly_exam.load_state",
             return_value={"last_run": last_run or "", "last_paper_ids": []},
         ):
        yield


def _simulate_until(
    start,
    end,
    *,
    job_seconds,
    job_kinds=("biweekly_exam",),
    today_pushes=None,
    due=False,
    last_run="",
    biweekly_slot=None,
):
    """模拟 scheduler wait/fire 循环（含 30s 尾间隔）。job_seconds=长任务占用。"""
    now = start
    consumed: set = set()
    fired: list[tuple[datetime.datetime, str, str | None]] = []
    skipped: list[tuple[datetime.datetime, str, str | None]] = []
    steps = 0
    with _sched_patches(due=due, last_run=last_run, biweekly_slot=biweekly_slot):
        while now < end and steps < 400:
            steps += 1
            target, kind, payload = _next_scheduled_event(
                now, consumed=consumed, today_pushes=today_pushes,
            )
            wait = (target - now).total_seconds()
            if wait >= 120:
                # 快进到即将到点，避免周末全日模拟被 30s 步数上限截断
                now += datetime.timedelta(seconds=wait - 90)
                continue
            if wait > 0:
                now += datetime.timedelta(seconds=wait)
            if kind == "cultivate" and payload:
                _merge_today_pushes_into_consumed(consumed, now, today_pushes)
                _apply_biweekly_cultivate_skip(consumed, now)
                if _cultivate_consumed_key(payload, _day_for_slot(now)) in consumed:
                    skipped.append((now, kind, payload))
                    now += datetime.timedelta(seconds=30)
                    continue
            fired.append((now, kind, payload))
            _note_event_fired(consumed, kind, payload, now)
            work = job_seconds if kind in job_kinds else 1
            now += datetime.timedelta(seconds=work + 30)
    return fired, skipped


def _no_weekend_cultivate(target, kind, payload, msg):
    """日推不得落在周六/周日。"""
    if kind != "cultivate":
        check(True, msg)
        return
    check(
        not _is_cultivate_skip_day(target.date()),
        f"{msg} (got {kind}/{payload} {target.isoformat()} weekday={target.weekday()})",
    )


def main():
    sat = datetime.datetime(2026, 8, 29, 0, 0, 0)  # Saturday
    sun = datetime.datetime(2026, 8, 30, 0, 0, 0)  # Sunday
    mon = datetime.datetime(2026, 8, 31, 0, 0, 0)  # Monday
    check(sat.weekday() == 5, "2026-08-29 is Saturday")
    check(sun.weekday() == 6, "2026-08-30 is Sunday")
    check(mon.weekday() == 0, "2026-08-31 is Monday")
    from cultivate_bank import PREGEN_SLOTS
    check("11:00" not in [t for t, _ in PREGEN_SLOTS], "PREGEN_SLOTS has no 11:00")
    check(all(t < "09:00" for t, _ in PREGEN_SLOTS), "all pregen before 09:00")

    # ── 1. 工作日过点同日：09:00 保持当天，不 +1 天 ──
    now = mon.replace(hour=10, minute=0)
    with _sched_patches():
        target, kind, payload = _next_scheduled_event(now)
    check(kind == "cultivate" and payload == "math",
          f"10:00 Monday next is cultivate/math (got {kind}/{payload})")
    check(target.date() == now.date() and target.hour == 9,
          f"overdue math stays Monday 09:00, not +1 day (got {target.isoformat()})")

    old_roll = now.replace(hour=9, minute=0) + datetime.timedelta(days=1)
    check(target.date() != old_roll.date(),
          "must not silently roll 09:00 math to Tuesday")

    # ── 2. 已消费则滚到明天，避免同槽连发 ──
    consumed = set()
    _note_event_fired(consumed, "cultivate", "math", now)
    with _sched_patches():
        t2, k2, p2 = _next_scheduled_event(now, consumed=consumed)
    math_again_today = (
        k2 == "cultivate" and p2 == "math" and t2.date() == now.date()
    )
    check(not math_again_today,
          f"consumed Monday math must not refire today (got {k2}/{p2} {t2})")

    # ── 3. 长任务从 08:30 压过 09:00：当日 math 仍会 fire ──
    fired, _skipped = _simulate_until(
        mon.replace(hour=7, minute=50),
        mon.replace(hour=12, minute=0),
        job_seconds=2 * 3600,
        job_kinds=("judge",),
    )
    kinds = [(t, k, p) for t, k, p in fired]
    math_fires = [t for t, k, p in fired if k == "cultivate" and p == "math"]
    check(not any(k == "github_push" for _, k, _ in fired),
          "github_push is not scheduled (trending daily push is off)")
    check(any(k == "judge" for _, k, _ in fired),
          f"Monday 08:30 still fires judge (events={kinds})")
    check(len(math_fires) == 1, f"math cultivate fires once (got {len(math_fires)}; events={kinds})")
    if math_fires:
        check(math_fires[0].date() == mon.date(),
              f"math runs Monday after 2h 08:30 job, not +1 day (got {math_fires[0].isoformat()})")
        check(math_fires[0] >= mon.replace(hour=10),
              f"math catch-up is after the long job (got {math_fires[0].isoformat()})")

    tuesday_math = [t for t in math_fires if t.date() == (mon + datetime.timedelta(days=1)).date()]
    check(not tuesday_math, "math must not be deferred to Tuesday")

    # ── 4. 15:00 / 19:00 同样同日补，不丢到明天 ──
    late = mon.replace(hour=20, minute=10)
    consumed_late = set()
    with _sched_patches():
        t_m, k_m, p_m = _next_scheduled_event(late, consumed=consumed_late)
    check((k_m, p_m) == ("cultivate", "math") and t_m.date() == mon.date(),
          f"20:10 still owes Monday math first (got {k_m}/{p_m} {t_m})")
    _note_event_fired(consumed_late, "cultivate", "math", late)
    with _sched_patches():
        t_c, k_c, p_c = _next_scheduled_event(late, consumed=consumed_late)
    check((k_c, p_c) == ("cultivate", "comm") and t_c.date() == mon.date(),
          f"then Monday 15:00 comm (got {k_c}/{p_c} {t_c})")
    _note_event_fired(consumed_late, "cultivate", "comm", late)
    with _sched_patches():
        t_r, k_r, p_r = _next_scheduled_event(late, consumed=consumed_late)
    check((k_r, p_r) == ("cultivate", "review") and t_r.date() == mon.date(),
          f"then Monday 19:00 review (got {k_r}/{p_r} {t_r})")

    # ── 5. 其它槽位仍按原规则滚动（judge / weekly；github_push 已停）──
    mon_1030 = datetime.datetime(2026, 8, 31, 10, 30, 0)
    with _sched_patches():
        all_mon = set()
        for _, subj in PUSH_SLOTS:
            _note_event_fired(all_mon, "cultivate", subj, mon_1030)
        t_peak, k_peak, p_peak = _next_scheduled_event(mon_1030, consumed=all_mon)
    peak_now = (
        k_peak in ("pregen", "judge", "bank_judge")
        and t_peak.date() == mon_1030.date()
        and 9 <= t_peak.hour < 18
    )
    check(not peak_now,
          f"weekday 10:30 after pushes has no same-day peak pregen/judge (got {k_peak}/{p_peak} {t_peak})")

    mon_0815 = datetime.datetime(2026, 8, 31, 8, 15, 0)
    with _sched_patches():
        t_j, k_j, p_j = _next_scheduled_event(mon_0815)
    check(k_j == "judge" and t_j.hour == 8 and t_j.minute == 30 and t_j.date() == mon_0815.date(),
          f"Monday 08:15 next is 08:30 judge (got {k_j}/{p_j} {t_j})")

    mon_morning = datetime.datetime(2026, 8, 31, 7, 0, 0)
    with _sched_patches():
        t_am, k_am, p_am = _next_scheduled_event(mon_morning)
    check(k_am != "github_push",
          f"Monday 07:00 must not schedule github_push (got {k_am} {t_am})")
    check(k_am == "judge" and t_am.hour == 8 and t_am.minute == 30 and t_am.date() == mon_morning.date(),
          f"Monday 07:00 next is 08:30 judge (got {k_am}/{p_am} {t_am})")

    sun_1930 = sun.replace(hour=19, minute=30)
    with _sched_patches():
        t_w, k_w, _ = _next_scheduled_event(sun_1930, consumed=set())
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

    # _daily_slot_target：工作日同日补；周末不补，滚到周一
    slot = _daily_slot_target(
        now, "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=True,
    )
    check(slot == now.replace(hour=9, minute=0, second=0, microsecond=0),
          f"_daily_slot_target catch-up keeps Monday 09:00 (got {slot})")
    slot_old = _daily_slot_target(
        now, "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=False,
    )
    check(slot_old.date() == (mon + datetime.timedelta(days=1)).date(),
          f"without catch-up, slot still +1 day (got {slot_old.date()})")

    sat_1016 = sat.replace(hour=10, minute=16)
    slot_sat = _daily_slot_target(
        sat_1016, "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=True,
    )
    check(slot_sat.date() == mon.date() and slot_sat.hour == 9,
          f"Saturday catch-up must not keep Sat 09:00, roll to Monday (got {slot_sat})")
    slot_sun = _daily_slot_target(
        sun.replace(hour=10, minute=0), "09:00", kind="cultivate", payload="math",
        consumed=set(), catch_up_same_day=True,
    )
    check(slot_sun.date() == mon.date() and slot_sun.hour == 9,
          f"Sunday catch-up must not keep Sun 09:00, roll to Monday (got {slot_sun})")

    # ── 7. 人工补发已落库 → 过点 09:00 不得再发（#5 consumed 洞）──
    now_1016 = mon.replace(hour=10, minute=16)
    manual_math = [{"subject": "math", "slot": "math", "item_id": 127}]
    with _sched_patches():
        t_dup, k_dup, p_dup = _next_scheduled_event(
            now_1016, consumed=set(), today_pushes=manual_math,
        )
    math_again = (
        k_dup == "cultivate" and p_dup == "math" and t_dup.date() == now_1016.date()
    )
    check(not math_again,
          f"existing Monday math push suppresses overdue 09:00 (got {k_dup}/{p_dup} {t_dup})")

    fired_dup, skipped_dup = _simulate_until(
        mon.replace(hour=7, minute=50),
        mon.replace(hour=12, minute=0),
        job_seconds=2 * 3600,
        job_kinds=("judge",),
        today_pushes=manual_math,
    )
    math_dup = [t for t, k, p in fired_dup if k == "cultivate" and p == "math"]
    check(len(math_dup) == 0,
          f"manual catch-up + scheduler recover must not both send (fired math={math_dup})")
    check(not any(k == "github_push" for _, k, _ in fired_dup),
          "github_push must not fire when math is already pushed")
    check(any(k == "judge" for _, k, _ in fired_dup),
          "08:30 judge still fires when math is already pushed")

    # 真 SQLite list_today_pushes：周一 10:12 已有 math → 10:16 不补发
    import tempfile
    import config as config_mod
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
                    pushed_at=utc_from_shanghai("2026-08-31", "10:12"),
                )
                rows = store.list_today_pushes(None, "2026-08-31")
                check(any((r.get("subject") or "").lower() == "math" for r in rows),
                      f"list_today_pushes has Monday math (n={len(rows)})")
                with _sched_patches():
                    t_db, k_db, p_db = _next_scheduled_event(
                        now_1016, consumed=set(), today_pushes=rows,
                    )
                db_math = (
                    k_db == "cultivate" and p_db == "math"
                    and t_db.date() == now_1016.date()
                )
                check(not db_math,
                      f"SQLite Monday math push blocks 09:00 catch-up (got {k_db}/{p_db} {t_db})")
            finally:
                reset_store()

    # ── 8. 每个周末（含非双周周日）三槽日推整日跳过，不按过期工作日回填 ──
    for label, day_dt in (("Saturday", sat), ("Sunday", sun)):
        check(_is_cultivate_skip_day(day_dt.date()), f"{label} is a cultivate skip day")
        with _sched_patches(due=False, last_run="2026-08-16T08:00:00"):
            check(_biweekly_day_skips_cultivate(day_dt.replace(hour=10, minute=0)),
                  f"{label} skips cultivate even when biweekly is not due")
            t_we, k_we, p_we = _next_scheduled_event(
                day_dt.replace(hour=10, minute=0), consumed=set(),
            )
        weekend_math = (
            k_we == "cultivate" and p_we == "math" and t_we.date() == day_dt.date()
        )
        check(not weekend_math,
              f"{label} 10:00 does not catch-up math (got {k_we}/{p_we} {t_we})")
        check(k_we != "cultivate" or t_we.date() != day_dt.date(),
              f"{label} next is not any same-day cultivate slot (got {k_we}/{p_we} {t_we})")
        _no_weekend_cultivate(t_we, k_we, p_we, f"{label} 10:00 cultivate target is weekday")

        # 尚未到点的未来槽（08:45 看 09/15/19）也不排周末
        with _sched_patches(due=False, last_run="2026-08-16T08:00:00"):
            t_early, k_early, p_early = _next_scheduled_event(
                day_dt.replace(hour=8, minute=45), consumed=set(),
            )
        check(not (k_early == "cultivate" and t_early.date() == day_dt.date()),
              f"{label} 08:45 does not schedule today's 09:00 math (got {k_early}/{p_early} {t_early})")

        fired_we, _ = _simulate_until(
            day_dt.replace(hour=7, minute=50),
            day_dt.replace(hour=20, minute=30),
            job_seconds=5,
            due=False,
            last_run="2026-08-16T08:00:00",
        )
        cult_we = [(t, p) for t, k, p in fired_we if k == "cultivate"]
        check(len(cult_we) == 0,
              f"{label} fires no math/comm/review even if overdue (got {cult_we})")
        fired_mid, _ = _simulate_until(
            day_dt.replace(hour=14, minute=50),
            day_dt.replace(hour=19, minute=20),
            job_seconds=5,
            due=False,
            last_run="2026-08-16T08:00:00",
        )
        cult_mid = [(t, p) for t, k, p in fired_mid if k == "cultivate"]
        check(len(cult_mid) == 0,
              f"{label} 15:00/19:00 slots are not catch-up-filled (got {cult_mid})")

    # 周五已消费三槽 → 下一档日推是周一，不是周六补洞
    fri = datetime.datetime(2026, 8, 28, 20, 10, 0)
    check(fri.weekday() == 4, "2026-08-28 is Friday")
    consumed_fri = set()
    for _, subj in PUSH_SLOTS:
        _note_event_fired(consumed_fri, "cultivate", subj, fri)
    with _sched_patches():
        t_fri, k_fri, p_fri = _next_scheduled_event(fri, consumed=consumed_fri)
    if k_fri == "cultivate":
        check(t_fri.date() == mon.date(),
              f"Friday after slots next cultivate is Monday not weekend (got {k_fri}/{p_fri} {t_fri})")
    else:
        # 可能先撞上周末 pregen/judge/weekly；再问周一早上应排 math
        with _sched_patches():
            t_mon9, k_mon9, p_mon9 = _next_scheduled_event(
                mon.replace(hour=8, minute=45), consumed=set(),
            )
        check(k_mon9 == "cultivate" and p_mon9 == "math" and t_mon9.date() == mon.date(),
              f"Monday 08:45 still schedules 09:00 math (got {k_mon9}/{p_mon9} {t_mon9})")

    # ── 9. 隔周到期周日：日推仍跳过，组卷 08:00 仍发（节奏不变）──
    due_sun = datetime.datetime(2026, 9, 13, 10, 0, 0)  # Sunday, next cycle
    check(due_sun.weekday() == 6, "2026-09-13 is Sunday")
    with _sched_patches(due=True, last_run="2026-08-30T10:10:00"):
        check(_biweekly_day_skips_cultivate(due_sun),
              "biweekly_is_due Sunday skips cultivate")
        t_due, k_due, p_due = _next_scheduled_event(due_sun, consumed=set())
    due_math = (
        k_due == "cultivate" and p_due == "math" and t_due.date() == due_sun.date()
    )
    check(not due_math,
          f"due Sunday 10:00 does not catch-up math with empty pushes (got {k_due}/{p_due} {t_due})")
    check(k_due != "cultivate",
          f"due Sunday next is not any cultivate slot (got {k_due}/{p_due})")

    due_sun_0800 = due_sun.replace(hour=8, minute=0, second=0, microsecond=0)
    with _sched_patches(due=True, last_run="2026-08-30T10:10:00",
                       biweekly_slot=_biweekly_at(due_sun_0800)):
        t_bw_due, k_bw_due, _ = _next_scheduled_event(
            due_sun.replace(hour=7, minute=0), consumed=set(),
        )
    check(k_bw_due != "github_push",
          f"due Sunday 07:00 must not schedule github_push (got {k_bw_due} {t_bw_due})")
    check(k_bw_due == "biweekly_exam" and t_bw_due == due_sun_0800,
          f"due Sunday still schedules biweekly 08:00 (got {k_bw_due} {t_bw_due})")

    fired_due, _ = _simulate_until(
        due_sun.replace(hour=7, minute=50),
        due_sun.replace(hour=20, minute=30),
        job_seconds=5,
        due=True,
        last_run="2026-08-30T10:10:00",
        biweekly_slot=_biweekly_at(due_sun_0800),
    )
    cult_due = [(t, p) for t, k, p in fired_due if k == "cultivate"]
    check(len(cult_due) == 0,
          f"due Sunday fires no math/comm/review even if overdue (got {cult_due})")
    check(not any(k == "github_push" for _, k, _ in fired_due),
          "due Sunday must not fire github_push")
    check(any(k == "biweekly_exam" for _, k, _ in fired_due),
          "due Sunday biweekly 08:00 still fires")

    # 发卷成功后 is_due 变 False，周末仍跳过（重启/同日补发）
    with _sched_patches(due=False, last_run="2026-09-13T10:10:00"):
        check(_biweekly_day_skips_cultivate(due_sun.replace(hour=15, minute=0)),
              "Sunday still skips after is_due flips")
        t_after, k_after, p_after = _next_scheduled_event(
            due_sun.replace(hour=15, minute=0), consumed=set(),
        )
    check(not (k_after == "cultivate" and p_after == "comm" and t_after.date() == due_sun.date()),
          f"after papers, 15:00 comm still skipped (got {k_after}/{p_after} {t_after})")

    # 非到期周日：日推同样跳过（不再只跳双周组卷日）
    off_sun = datetime.datetime(2026, 8, 16, 10, 0, 0)  # Sunday, 7 days after 8/9
    check(off_sun.weekday() == 6, "2026-08-16 is Sunday")
    with _sched_patches(due=False, last_run="2026-08-09T08:00:00"):
        check(_biweekly_day_skips_cultivate(off_sun),
              "off-week Sunday also skips cultivate")
        t_off, k_off, p_off = _next_scheduled_event(off_sun, consumed=set())
    check(not (k_off == "cultivate" and p_off == "math" and t_off.date() == off_sun.date()),
          f"non-biweekly Sunday must not catch-up math (got {k_off}/{p_off} {t_off})")

    # 到期周一不跳（周末才跳日推；双周 due 标志不把工作日关掉）
    due_mon = datetime.datetime(2026, 9, 14, 10, 0, 0)
    with _sched_patches(due=True, last_run="2026-08-30T10:10:00"):
        check(not _biweekly_day_skips_cultivate(due_mon),
              "Monday is not a weekend skip day")
        t_dm, k_dm, p_dm = _next_scheduled_event(due_mon, consumed=set())
    check(k_dm == "cultivate" and p_dm == "math" and t_dm.date() == due_mon.date(),
          f"Monday still catch-up math even if biweekly_is_due (got {k_dm}/{p_dm} {t_dm})")

    # ── 10. 调度器不再排出 github_push（任意抽样时刻）──
    sample_times = [
        datetime.datetime(2026, 8, 31, 7, 59, 0),
        datetime.datetime(2026, 8, 31, 8, 0, 0),
        datetime.datetime(2026, 8, 31, 8, 1, 0),
        datetime.datetime(2026, 9, 13, 7, 59, 0),
        datetime.datetime(2026, 9, 13, 8, 0, 0),
    ]
    with _sched_patches():
        for sample in sample_times:
            _, k_off, _ = _next_scheduled_event(sample, consumed=set())
            check(k_off != "github_push",
                  f"{sample.isoformat()} must not next-schedule github_push (got {k_off})")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL SCHEDULER SAME-DAY TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
