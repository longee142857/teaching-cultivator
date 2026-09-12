# -*- coding: utf-8 -*-
"""验收 zhou_comm.db：schema + 书序可查询。未通过不得设 ZHOU_COMM_ACCEPTED=1。"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from learner.atom_book import BOOK_ZHOU, BOOK_FAN, accept_report, book_accepted

    book = BOOK_FAN if "--fan" in sys.argv else BOOK_ZHOU
    report = accept_report(book)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = bool(report.get("schema_ok")) and bool(report.get("book_order_ok"))
    accepted = book_accepted(book)
    if not report.get("exists"):
        print("NOT ACCEPTED: 原子库文件不存在。推进模式保持关闭。")
        return 2
    if not ok:
        print(f"NOT ACCEPTED: schema/书序失败 ({report.get('schema_reason')})")
        return 2
    if not accepted:
        print("SCHEMA OK but ACCEPTED env=0 — 人工抽检通过后再设 ZHOU_COMM_ACCEPTED=1")
        return 1
    print("ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
