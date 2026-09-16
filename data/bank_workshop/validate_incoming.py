#!/usr/bin/env python3
"""Hard-check workshop incoming JSON (+ optional *.judge.json) against syllabi."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_COMM = "https://raw.githubusercontent.com/longee142857/teaching-cultivator/master/data/syllabus_comm.json"
DEFAULT_MATH = "https://raw.githubusercontent.com/longee142857/teaching-cultivator/master/data/syllabus_math.json"
ALLOWED_FORMS = {"blank", "proof_outline"}
ALLOWED_GOALS = {"compute", "construct"}
MCQ_PAT = re.compile(
    r"(?i)(选择题|单选|多选|\bA[\.．、\)]\s*.+\bB[\.．、\)]|\([A-D]\)\s|选项[ABCD]|recognize)",
)

ROOT = Path(__file__).resolve().parents[2]


def load_syllabus(path_or_url: str) -> dict:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": "bank-workshop-validate"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(path_or_url).read_text(encoding="utf-8"))


def index_syllabus(data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for l2, kp in (data.get("kps") or {}).items():
        for l3 in kp.get("l3") or []:
            out[l3["id"]] = {"l2": l2, "l3_name": l3.get("name"), "subject": data.get("subject")}
    return out


def load_item(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_item(item: dict, syll: dict[str, dict], require_judge_accept: bool, judge: dict | None) -> list[str]:
    errs: list[str] = []
    l3_id = item.get("l3_id") or ""
    if l3_id not in syll:
        errs.append(f"l3_id not in syllabus: {l3_id}")
    else:
        expected_l2 = syll[l3_id]["l2"]
        if item.get("l2") and item.get("l2") != expected_l2:
            errs.append(f"l2 mismatch: item={item.get('l2')} syllabus={expected_l2}")
        subj = item.get("subject")
        if subj and syll[l3_id].get("subject") and subj != syll[l3_id]["subject"]:
            errs.append(f"subject mismatch: item={subj} syllabus={syll[l3_id]['subject']}")

    form = item.get("item_form")
    if form not in ALLOWED_FORMS:
        errs.append(f"item_form must be blank|proof_outline, got {form!r}")

    goal = item.get("ability_goal")
    if goal not in ALLOWED_GOALS:
        errs.append(f"ability_goal must be compute|construct, got {goal!r}")

    if MCQ_PAT.search(str(item.get("question") or "")):
        errs.append("MCQ/recognize pattern detected in question")
    if str(item.get("item_form") or "").lower() in {"mcq", "recognize", "choice"}:
        errs.append("forbidden item_form (mcq/recognize)")

    diff = item.get("difficulty")
    if diff not in (None, "", "hit"):
        if str(diff).lower() == "basic":
            errs.append("difficulty must be empty or hit (not basic)")

    cdps = item.get("cdps")
    try:
        if cdps is None or int(cdps) < 2:
            errs.append(f"cdps must be >= 2, got {cdps!r}")
    except (TypeError, ValueError):
        errs.append(f"cdps not int-like: {cdps!r}")

    atom_id = item.get("atom_id") or ""
    book_id = item.get("book_id") or ""
    if atom_id:
        if not str(atom_id).startswith("zhou."):
            errs.append(f"atom_id if set must be zhou.*, got {atom_id!r}")
        if book_id != "zhou_comm":
            errs.append(f"book_id must be zhou_comm when atom_id set, got {book_id!r}")

    meta = item.get("meta") or {}
    if isinstance(meta, dict):
        src = meta.get("source")
        if src and src != "cloud_cursor_workshop":
            errs.append(f"meta.source expected cloud_cursor_workshop, got {src!r}")

    for req in ("id", "subject", "l2", "l3_id", "question", "answer", "techniques", "solution"):
        if not item.get(req) and item.get(req) != 0:
            errs.append(f"missing required field: {req}")

    if require_judge_accept:
        if not judge:
            errs.append("missing companion *.judge.json")
        else:
            dec = judge.get("decision")
            if dec != "accept":
                errs.append(f"judge.decision must be accept for keep, got {dec!r}")

    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate bank_workshop incoming items")
    ap.add_argument(
        "incoming_dir",
        nargs="?",
        default=str(ROOT / "data" / "bank_workshop" / "incoming" / "2026-09-16"),
    )
    ap.add_argument("--syllabus-comm", default=DEFAULT_COMM)
    ap.add_argument("--syllabus-math", default=DEFAULT_MATH)
    ap.add_argument("--require-judge-accept", action="store_true", default=True)
    ap.add_argument("--no-require-judge-accept", dest="require_judge_accept", action="store_false")
    args = ap.parse_args()

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
    for path in files:
        item = load_item(path)
        judge_path = path.with_name(path.stem + ".judge.json")
        judge = load_item(judge_path) if judge_path.exists() else None
        errs = check_item(item, syll, args.require_judge_accept, judge)
        if errs:
            failed += 1
            print(f"FAIL {path.name}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK   {path.name}")

    print(f"checked={len(files)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
