#!/usr/bin/env python3
"""Safe atom inserter with gate checks for zhou_comm.db."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"definition", "theorem", "formula", "procedure", "caveat", "example"}
ALLOWED_ROLES = {"core", "context", "counterexample"}
MAX_CORE_PARAS = 6


class AtomInsertError(ValueError):
    pass


def load_syllabus_l3_ids(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            i = obj.get("id")
            if isinstance(i, str):
                ids.add(i)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return ids


def validate_atom(
    atom: dict,
    existing_paras: set[str],
    syllabus: set[str],
    *,
    expect_chapter: int | None = None,
    expect_day: int | None = None,
) -> None:
    aid = atom.get("id")
    if not aid or not isinstance(aid, str):
        raise AtomInsertError("missing id")
    if not aid.startswith("zhou.ch"):
        raise AtomInsertError(f"{aid}: id must start with zhou.ch")
    if any(c.isupper() for c in aid):
        raise AtomInsertError(f"{aid}: id must be lowercase")
    if " " in aid or "/" in aid:
        raise AtomInsertError(f"{aid}: id has illegal chars")
    if atom.get("type") not in ALLOWED_TYPES:
        raise AtomInsertError(f"{aid}: bad type {atom.get('type')}")
    if not atom.get("name") or not atom.get("statement"):
        raise AtomInsertError(f"{aid}: name/statement required")
    if expect_chapter is not None and atom.get("chapter") != expect_chapter:
        raise AtomInsertError(f"{aid}: chapter must be {expect_chapter}")
    if expect_day is not None and atom.get("created_day") != expect_day:
        raise AtomInsertError(f"{aid}: created_day must be {expect_day}")
    spans = atom.get("spans") or []
    if not spans:
        raise AtomInsertError(f"{aid}: no spans")
    cores = [s for s in spans if s.get("role") == "core"]
    if not cores:
        raise AtomInsertError(f"{aid}: REJECT — no role=core span")
    if len(cores) > MAX_CORE_PARAS:
        raise AtomInsertError(f"{aid}: too many core spans ({len(cores)}>{MAX_CORE_PARAS})")
    seen = set()
    for s in spans:
        pid = s.get("paragraph_id")
        role = s.get("role")
        if role not in ALLOWED_ROLES:
            raise AtomInsertError(f"{aid}: bad role {role}")
        if not pid or pid not in existing_paras:
            raise AtomInsertError(f"{aid}: unknown paragraph_id {pid}")
        if pid in seen:
            raise AtomInsertError(f"{aid}: duplicate span {pid}")
        seen.add(pid)
    for m in atom.get("l3") or []:
        lid = m.get("l3_id")
        conf = m.get("confidence")
        if lid not in syllabus:
            raise AtomInsertError(f"{aid}: l3_id {lid} not in syllabus")
        if not isinstance(conf, (int, float)) or not (0 <= float(conf) <= 1):
            raise AtomInsertError(f"{aid}: bad confidence")


def insert_atoms(
    conn: sqlite3.Connection,
    atoms: list[dict],
    syllabus: set[str],
    *,
    expect_chapter: int | None = None,
    expect_day: int | None = None,
) -> dict:
    cur = conn.cursor()
    paras = {r[0] for r in cur.execute("SELECT id FROM paragraphs")}
    inserted = []
    rejected = []
    for atom in atoms:
        try:
            validate_atom(
                atom,
                paras,
                syllabus,
                expect_chapter=expect_chapter,
                expect_day=expect_day,
            )
        except AtomInsertError as e:
            rejected.append(str(e))
            continue
        aid = atom["id"]
        exists = cur.execute("SELECT 1 FROM atoms WHERE id=?", (aid,)).fetchone()
        if exists:
            rejected.append(f"{aid}: already exists")
            continue
        aliases = atom.get("aliases") or []
        cur.execute(
            "INSERT INTO atoms(id,type,name,statement,chapter,aliases_json,created_day) VALUES(?,?,?,?,?,?,?)",
            (
                aid,
                atom["type"],
                atom["name"],
                atom["statement"],
                atom["chapter"],
                json.dumps(aliases, ensure_ascii=False),
                atom["created_day"],
            ),
        )
        for s in atom["spans"]:
            cur.execute(
                "INSERT INTO atom_spans(atom_id,paragraph_id,role) VALUES(?,?,?)",
                (aid, s["paragraph_id"], s["role"]),
            )
        for m in atom.get("l3") or []:
            cur.execute(
                "INSERT INTO atom_l3(atom_id,l3_id,confidence) VALUES(?,?,?)",
                (aid, m["l3_id"], float(m["confidence"])),
            )
        for term in atom.get("terms") or []:
            cur.execute(
                "INSERT OR IGNORE INTO terms(term,atom_id) VALUES(?,?)",
                (term, aid),
            )
        inserted.append(aid)
    conn.commit()
    return {"inserted": inserted, "rejected": rejected}


def gate_report(conn: sqlite3.Connection, *, created_day: int, chapter: int) -> dict:
    cur = conn.cursor()
    n_atoms = cur.execute(
        "SELECT COUNT(*) FROM atoms WHERE created_day=? AND chapter=?",
        (created_day, chapter),
    ).fetchone()[0]
    n_core = cur.execute(
        """
        SELECT COUNT(DISTINCT a.id) FROM atoms a
        JOIN atom_spans s ON a.id=s.atom_id AND s.role='core'
        WHERE a.created_day=? AND a.chapter=?
        """,
        (created_day, chapter),
    ).fetchone()[0]
    n_no_core = cur.execute(
        """
        SELECT COUNT(*) FROM atoms a
        WHERE a.created_day=? AND a.chapter=?
          AND NOT EXISTS (
            SELECT 1 FROM atom_spans s WHERE s.atom_id=a.id AND s.role='core'
          )
        """,
        (created_day, chapter),
    ).fetchone()[0]
    pct = (100.0 * n_core / n_atoms) if n_atoms else 0.0
    return {
        f"atoms_day{created_day}_ch{chapter}": n_atoms,
        "with_core": n_core,
        "without_core": n_no_core,
        "pct_with_core": pct,
        "pass_count_gate": n_atoms >= 25,
        "pass_core_gate": pct >= 90.0 and n_no_core == 0,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/workspace/zhou-comm-atoms/zhou_comm.db")
    ap.add_argument("--atoms", required=True)
    ap.add_argument("--syllabus", default="/workspace/zhou-comm-atoms/sources/syllabus_comm.json")
    ap.add_argument("--expect-chapter", type=int, default=None)
    ap.add_argument("--expect-day", type=int, default=None)
    args = ap.parse_args()
    atoms = json.loads(Path(args.atoms).read_text(encoding="utf-8"))
    syllabus = load_syllabus_l3_ids(Path(args.syllabus))
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    result = insert_atoms(
        conn,
        atoms,
        syllabus,
        expect_chapter=args.expect_chapter,
        expect_day=args.expect_day,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.expect_day is not None and args.expect_chapter is not None:
        print(json.dumps(gate_report(conn, created_day=args.expect_day, chapter=args.expect_chapter), ensure_ascii=False, indent=2))
