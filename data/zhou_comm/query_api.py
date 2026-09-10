#!/usr/bin/env python3
"""Read-only smoke queries for the 周炯槃 atom SQLite (delivery candidate).

Not wired to cultivate / RAG / KB_PATH. Stdlib only.

Usage:
    python query_api.py demo
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "zhou_comm.db"


def _die_missing() -> int:
    print(
        "zhou_comm.db is missing. This commit is a delivery-candidate placeholder.\n"
        "Extract zhou_comm_atoms_delivery.tar.gz into data/zhou_comm/ and re-run.\n"
        "See MISSING_ASSETS.md.",
        file=sys.stderr,
    )
    return 2


def demo() -> int:
    if not DB_PATH.is_file():
        return _die_missing()
    size = DB_PATH.stat().st_size
    print(f"db: {DB_PATH} ({size} bytes)")
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        print("tables:", ", ".join(tables) or "(none)")
        for name in tables:
            n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            print(f"  {name}: {n}")
    finally:
        con.close()
    return 0


def main(argv: list[str]) -> int:
    cmd = (argv[1] if len(argv) > 1 else "demo").strip()
    if cmd in {"-h", "--help", "help"}:
        print(__doc__.strip())
        return 0
    if cmd != "demo":
        print(f"unknown command: {cmd}", file=sys.stderr)
        print("usage: python query_api.py demo", file=sys.stderr)
        return 2
    return demo()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
