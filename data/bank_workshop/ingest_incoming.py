#!/usr/bin/env python3
"""Import accepted workshop JSON into teaching.db (manual; never called by cultivate*.py)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_incoming import (  # noqa: E402
    DEFAULT_COMM,
    DEFAULT_MATH,
    check_item,
    index_syllabus,
    load_item,
    load_syllabus,
)

WORKSHOP_SOURCE = "cloud_cursor_workshop"


def _local_or_default(name: str, fallback: str) -> str:
    p = ROOT / "data" / name
    return str(p) if p.exists() else fallback


def stamp_source(item: dict) -> dict:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    else:
        meta = dict(meta)
    meta["source"] = WORKSHOP_SOURCE
    wid = (item.get("id") or "").strip()
    if wid:
        meta.setdefault("workshop_id", wid)
    return meta


def normalize_solution(item: dict) -> dict:
    sol = item.get("solution")
    if isinstance(sol, dict):
        out = dict(sol)
        out.setdefault("final_answer", item.get("answer") or "")
        if "techniques_used" not in out:
            out["techniques_used"] = list(item.get("techniques") or [])
        return out
    text = str(sol or "").strip()
    return {
        "steps": [{"id": "s1", "text": text}] if text else [],
        "final_answer": item.get("answer") or "",
        "techniques_used": list(item.get("techniques") or []),
    }


def _solution_parts(item: dict) -> list[str]:
    sol = item.get("solution")
    if isinstance(sol, dict):
        parts = []
        for s in sol.get("steps") or []:
            if isinstance(s, dict):
                text = str(s.get("text") or "").strip()
            else:
                text = str(s or "").strip()
            if text:
                parts.append(text)
        if parts:
            return parts
        fa = str(sol.get("final_answer") or "").strip()
        return [fa] if fa else []
    text = str(sol or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?:^|\s)\d+\)\s*", text) if p.strip()]
    return parts or [text]


def normalize_cdps(item: dict) -> list[dict]:
    raw = item.get("cdps")
    if isinstance(raw, list):
        return [dict(x) if isinstance(x, dict) else {"id": f"cdp{i+1}", "prompt": str(x)}
                for i, x in enumerate(raw)]
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    techs = [str(t) for t in (item.get("techniques") or []) if str(t).strip()]
    parts = _solution_parts(item)
    if n < 2:
        n = max(2, len(parts))
    while len(parts) < n:
        parts.append(str(item.get("answer") or f"step {len(parts)+1}"))
    out: list[dict] = []
    for i in range(n):
        tech = techs[i] if i < len(techs) else (techs[0] if techs else "step")
        out.append(
            {
                "id": f"cdp{i+1}",
                "prompt": parts[i][:240],
                "expected": parts[i],
                "technique": tech,
                "depends_on": [f"cdp{i}"] if i else [],
            }
        )
    return out


def check_atom_in_book(item: dict) -> list[str]:
    if (item.get("subject") or "").strip().lower() != "comm":
        return []
    atom_id = (item.get("atom_id") or "").strip()
    book_id = (item.get("book_id") or "zhou_comm").strip() or "zhou_comm"
    try:
        from learner.atom_book import get_atom, schema_ok
    except Exception as e:
        return [f"atom_book import failed: {e}"]
    ok, why = schema_ok(book_id)
    if not ok:
        return [f"Zhou book unavailable ({book_id}): {why}"]
    if not get_atom(atom_id, book_id):
        return [f"atom_id not in Zhou book: {atom_id}"]
    return []


def import_one(
    item: dict,
    judge: dict | None,
    *,
    apply: bool,
    require_judge_accept: bool,
) -> dict[str, Any]:
    store = None
    if apply:
        from learner.db import get_store

        store = get_store()
    meta = stamp_source(item)
    techs = list(item.get("techniques") or [])
    sol = normalize_solution(item)
    cdps = normalize_cdps(item)
    subject = (item.get("subject") or "").strip().lower()
    payload = {
        "subject": subject,
        "question": item.get("question") or "",
        "answer": item.get("answer") or "",
        "difficulty": item.get("difficulty") or "",
        "kp": item.get("l2") or "",
        "l3_id": item.get("l3_id") or "",
        "item_form": item.get("item_form") or "",
        "ability_goal": item.get("ability_goal") or "",
        "techniques": techs,
        "solution": sol,
        "cdps": cdps,
        "meta": meta,
        "status": "ready",
        "atom_id": item.get("atom_id") or "",
        "book_id": item.get("book_id") or "",
    }
    if not apply:
        return {"ok": True, "dry_run": True, "workshop_id": item.get("id"), "payload": payload}

    item_id = store.insert_bank_item(**payload)
    judge_applied = False
    if require_judge_accept and judge and (judge.get("decision") or "") == "accept":
        store.apply_judge_verdict(
            item_id,
            verdict="pass",
            reasons=list(judge.get("reasons") or ["workshop accept"]),
            confidence=1.0,
            details={"workshop_id": item.get("id"), "source": WORKSHOP_SOURCE},
        )
        judge_applied = True
    row = store.get_item(item_id) or {}
    return {
        "ok": True,
        "dry_run": False,
        "item_id": item_id,
        "workshop_id": item.get("id"),
        "quality_tier": row.get("quality_tier"),
        "judge_applied": judge_applied,
        "source": (row.get("meta") or {}).get("source") if isinstance(row.get("meta"), dict) else WORKSHOP_SOURCE,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Ingest accepted bank_workshop items into teaching.db (manual)"
    )
    ap.add_argument(
        "incoming_dir",
        nargs="?",
        default=str(ROOT / "data" / "bank_workshop" / "incoming" / "2026-09-16"),
    )
    ap.add_argument("--syllabus-comm", default=_local_or_default("syllabus_comm.json", DEFAULT_COMM))
    ap.add_argument("--syllabus-math", default=_local_or_default("syllabus_math.json", DEFAULT_MATH))
    ap.add_argument("--require-judge-accept", action="store_true", default=True)
    ap.add_argument("--no-require-judge-accept", dest="require_judge_accept", action="store_false")
    ap.add_argument("--apply", action="store_true", help="write teaching.db; default is dry-run")
    args = ap.parse_args(argv)

    syll: dict[str, dict] = {}
    syll.update(index_syllabus(load_syllabus(args.syllabus_comm)))
    syll.update(index_syllabus(load_syllabus(args.syllabus_math)))

    d = Path(args.incoming_dir)
    if not d.is_absolute():
        d = ROOT / d
    if not d.exists():
        print(f"incoming dir missing: {d}", file=sys.stderr)
        return 2

    files = sorted(p for p in d.glob("*.json") if not p.name.endswith(".judge.json"))
    if not files:
        print(f"no item JSON in {d}")
        return 0

    failed = 0
    imported = 0
    for path in files:
        item = load_item(path)
        judge_path = path.with_name(path.stem + ".judge.json")
        judge = load_item(judge_path) if judge_path.exists() else None
        errs = check_item(item, syll, args.require_judge_accept, judge)
        errs.extend(check_atom_in_book(item))
        if (item.get("subject") or "").strip().lower() == "review":
            if "workshop must not produce subject=review" not in errs:
                errs.append("workshop must not produce subject=review")
        if errs:
            failed += 1
            print(f"FAIL {path.name}")
            for e in errs:
                print(f"  - {e}")
            continue
        try:
            result = import_one(
                item,
                judge,
                apply=args.apply,
                require_judge_accept=args.require_judge_accept,
            )
        except Exception as e:
            failed += 1
            print(f"FAIL {path.name}")
            print(f"  - ingest error: {e}")
            continue
        imported += 1
        tag = "DRY" if result.get("dry_run") else "IN"
        extra = result.get("item_id") or result.get("workshop_id") or ""
        tier = result.get("quality_tier") or ("pending until --apply" if result.get("dry_run") else "")
        print(f"{tag}  {path.name} {extra} tier={tier}")

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} checked={len(files)} imported={imported} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
