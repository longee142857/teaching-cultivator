# -*- coding: utf-8 -*-
"""Dry-run / apply backfill of attempts.push_id from pushes by kp + time."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SH = timezone(timedelta(hours=8))


def day_of(ts: str) -> str:
    try:
        dt = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        return dt.astimezone(SH).strftime("%Y-%m-%d")
    except Exception:
        return (ts or "")[:10]


def pick_push(con: sqlite3.Connection, user_id: str, kp: str, answered_at: str):
    """Prefer same Shanghai day + nearest push before answer; else nearest before answer."""
    day = day_of(answered_at)
    # 公共课 learner_id 为空；个人 push 也可能是 staffId
    q = """
        select p.id as push_id, p.item_id, p.day, p.pushed_at, i.kp
        from pushes p
        join items i on i.id = p.item_id
        where (p.learner_id = ? or p.learner_id is null or p.learner_id = '')
          and i.kp = ?
          and p.pushed_at <= ?
        order by
          case when p.day = ? then 0 else 1 end,
          p.pushed_at desc
        limit 1
    """
    row = con.execute(q, (user_id, kp, answered_at, day)).fetchone()
    if row:
        return row
    # 回退：该 KP 任意最近 push（作答早于迁移推送时间戳时）
    q2 = """
        select p.id as push_id, p.item_id, p.day, p.pushed_at, i.kp
        from pushes p
        join items i on i.id = p.item_id
        where (p.learner_id = ? or p.learner_id is null or p.learner_id = '')
          and i.kp = ?
        order by abs(julianday(p.pushed_at) - julianday(?))
        limit 1
    """
    return con.execute(q2, (user_id, kp, answered_at or "1970-01-01")).fetchone()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/teaching.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="data/backfill_push_id_report.json")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    miss = con.execute(
        """
        select id, user_id, knowledge_point, answered_at, item_id
        from attempts
        where push_id is null or push_id = ''
        order by answered_at asc, id asc
        """
    ).fetchall()

    planned = []
    unmatched = []
    for a in miss:
        kp = (a["knowledge_point"] or "").strip()
        if not kp or kp == "未分类":
            unmatched.append({"attempt_id": a["id"], "reason": "no_kp"})
            continue
        hit = pick_push(con, a["user_id"], kp, a["answered_at"] or "")
        if not hit:
            unmatched.append(
                {
                    "attempt_id": a["id"],
                    "reason": "no_push",
                    "kp": kp,
                    "answered_at": a["answered_at"],
                }
            )
            continue
        planned.append(
            {
                "attempt_id": a["id"],
                "push_id": int(hit["push_id"]),
                "item_id": int(hit["item_id"]),
                "kp": kp,
                "push_day": hit["day"],
                "answer_day": day_of(a["answered_at"] or ""),
                "same_day": hit["day"] == day_of(a["answered_at"] or ""),
            }
        )

    report = {
        "missing_before": len(miss),
        "planned": len(planned),
        "unmatched": len(unmatched),
        "same_day": sum(1 for p in planned if p["same_day"]),
        "cross_day": sum(1 for p in planned if not p["same_day"]),
        "unmatched_sample": unmatched[:20],
        "planned_sample": planned[:10],
        "applied": False,
    }

    if args.apply and planned:
        for p in planned:
            con.execute(
                "update attempts set push_id=?, item_id=coalesce(item_id, ?) where id=?",
                (p["push_id"], p["item_id"], p["attempt_id"]),
            )
        con.commit()
        report["applied"] = True
        left = con.execute(
            "select count(*) c from attempts where push_id is null or push_id=''"
        ).fetchone()["c"]
        report["missing_after"] = left

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in report if k not in ("unmatched_sample", "planned_sample")}, ensure_ascii=False, indent=2))
    print("report", args.report)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
