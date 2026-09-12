# -*- coding: utf-8 -*-
"""只读原子库（zhou_comm.db / fan_comm.db）。禁止写入。"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

REQUIRED_TABLES = (
    "meta",
    "pages",
    "paragraphs",
    "atoms",
    "atom_spans",
    "atom_l3",
)

BOOK_ZHOU = "zhou_comm"
BOOK_FAN = "fan_comm"
L3_MIN_CONF = 0.6


def _data_dir() -> str:
    try:
        from config import DATA_DIR

        return DATA_DIR
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _first_db(*paths: str) -> str:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    for p in paths:
        if p:
            return p
    return ""


def book_db_path(book_id: str = BOOK_ZHOU) -> str:
    """Env 覆盖（显式路径，即使文件暂缺）→ git 交付路径 → 运行时副本 data/atom_books/。"""
    bid = (book_id or BOOK_ZHOU).strip() or BOOK_ZHOU
    data = _data_dir()
    if bid == BOOK_FAN:
        env = os.environ.get("FAN_COMM_DB", "").strip()
        if env:
            return env
        return _first_db(
            os.path.join(data, "fan_comm", "fan_comm.db"),
            os.path.join(data, "atom_books", "fan_comm.db"),
        )
    env = os.environ.get("ZHOU_COMM_DB", "").strip()
    if env:
        return env
    return _first_db(
        os.path.join(data, "zhou_comm", "zhou_comm.db"),
        os.path.join(data, "atom_books", "zhou_comm.db"),
    )


def _connect_ro(path: str) -> sqlite3.Connection:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(path)
    uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def schema_ok(book_id: str = BOOK_ZHOU) -> tuple[bool, str]:
    path = book_db_path(book_id)
    if not os.path.isfile(path):
        return False, f"missing:{path}"
    try:
        conn = _connect_ro(path)
    except Exception as e:
        return False, f"open:{type(e).__name__}:{e}"
    try:
        names = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = [t for t in REQUIRED_TABLES if t not in names]
        if missing:
            return False, f"missing_tables:{','.join(missing)}"
        chk = conn.execute("PRAGMA integrity_check").fetchone()
        if not chk or str(chk[0]).lower() != "ok":
            msg = str(chk[0]) if chk else "?"
            # FTS5 content tables try to rebuild the inverted index here;
            # that write is forbidden on the read-only handle we must keep.
            low = msg.lower()
            if not ("fts5" in low and "readonly" in low):
                return False, f"integrity:{msg}"
        n_atoms = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]
        if int(n_atoms) < 1:
            return False, "no_atoms"
        return True, path
    except Exception as e:
        return False, f"schema:{type(e).__name__}:{e}"
    finally:
        conn.close()


def book_accepted(book_id: str = BOOK_ZHOU) -> bool:
    """人工验收闸。schema 可用仍不够：须 env 显式放行。"""
    if book_id == BOOK_FAN:
        flag = os.environ.get("FAN_COMM_ACCEPTED", "0").strip().lower()
    else:
        flag = os.environ.get("ZHOU_COMM_ACCEPTED", "0").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    ok, _ = schema_ok(book_id)
    return ok


def list_atoms_in_book_order(book_id: str = BOOK_ZHOU) -> list[dict[str, Any]]:
    ok, why = schema_ok(book_id)
    if not ok:
        return []
    path = book_db_path(book_id)
    conn = _connect_ro(path)
    try:
        rows = conn.execute(
            """
            SELECT a.id, a.type, a.name, a.statement, a.chapter,
                   MIN(p.print_page) AS print_page,
                   MIN(p.seq) AS seq
            FROM atoms a
            JOIN atom_spans s ON s.atom_id = a.id AND s.role = 'core'
            JOIN paragraphs p ON p.id = s.paragraph_id
            GROUP BY a.id
            ORDER BY a.chapter ASC, print_page ASC, seq ASC, a.id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_atom(atom_id: str, book_id: str = BOOK_ZHOU) -> dict[str, Any] | None:
    aid = (atom_id or "").strip()
    if not aid:
        return None
    ok, _ = schema_ok(book_id)
    if not ok:
        return None
    conn = _connect_ro(book_db_path(book_id))
    try:
        row = conn.execute(
            "SELECT id, type, name, statement, chapter FROM atoms WHERE id=?",
            (aid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def best_l3(atom_id: str, book_id: str = BOOK_ZHOU) -> dict[str, Any] | None:
    aid = (atom_id or "").strip()
    if not aid:
        return None
    ok, _ = schema_ok(book_id)
    if not ok:
        return None
    conn = _connect_ro(book_db_path(book_id))
    try:
        row = conn.execute(
            """
            SELECT l3_id, confidence FROM atom_l3
            WHERE atom_id=? AND confidence >= ?
            ORDER BY confidence DESC, l3_id ASC LIMIT 1
            """,
            (aid, L3_MIN_CONF),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def core_spans(atom_id: str, book_id: str = BOOK_ZHOU) -> list[dict[str, Any]]:
    aid = (atom_id or "").strip()
    if not aid:
        return []
    ok, _ = schema_ok(book_id)
    if not ok:
        return []
    conn = _connect_ro(book_db_path(book_id))
    try:
        rows = conn.execute(
            """
            SELECT s.atom_id, s.paragraph_id, s.role,
                   p.print_page, p.seq, p.text, p.kind
            FROM atom_spans s
            JOIN paragraphs p ON p.id = s.paragraph_id
            WHERE s.atom_id=? AND s.role='core'
            ORDER BY p.print_page ASC, p.seq ASC
            """,
            (aid,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def next_atom_after(atom_id: str, book_id: str = BOOK_ZHOU) -> str:
    ordered = list_atoms_in_book_order(book_id)
    if not ordered:
        return ""
    aid = (atom_id or "").strip()
    if not aid:
        return str(ordered[0]["id"])
    for i, row in enumerate(ordered):
        if str(row["id"]) == aid:
            if i + 1 < len(ordered):
                return str(ordered[i + 1]["id"])
            return ""
    return str(ordered[0]["id"])


def first_atom_id(book_id: str = BOOK_ZHOU) -> str:
    ordered = list_atoms_in_book_order(book_id)
    return str(ordered[0]["id"]) if ordered else ""


def accept_report(book_id: str = BOOK_ZHOU) -> dict[str, Any]:
    path = book_db_path(book_id)
    ok, why = schema_ok(book_id)
    report: dict[str, Any] = {
        "book_id": book_id,
        "path": path,
        "exists": os.path.isfile(path),
        "schema_ok": ok,
        "schema_reason": why,
        "accepted_env": book_accepted(book_id),
        "n_pages": 0,
        "n_paragraphs": 0,
        "n_atoms": 0,
        "n_mapped_l3": 0,
        "book_order_ok": False,
        "sample": [],
    }
    if not ok:
        return report
    conn = _connect_ro(path)
    try:
        report["n_pages"] = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        report["n_paragraphs"] = int(
            conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
        )
        report["n_atoms"] = int(conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0])
        report["n_mapped_l3"] = int(
            conn.execute(
                "SELECT COUNT(DISTINCT atom_id) FROM atom_l3 WHERE confidence>=?",
                (L3_MIN_CONF,),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    ordered = list_atoms_in_book_order(book_id)
    report["book_order_ok"] = bool(ordered)
    report["n_ordered"] = len(ordered)
    report["sample"] = [
        {
            "id": r["id"],
            "chapter": r["chapter"],
            "print_page": r["print_page"],
            "seq": r["seq"],
        }
        for r in ordered[:5]
    ]
    return report
