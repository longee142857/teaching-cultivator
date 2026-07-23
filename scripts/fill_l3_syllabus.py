"""Fill syllabus_*.json L3 from _l3_catalog (BIG-TEACH-011b).

Overwrite each L2's meta["l3"] with catalog entries; validate; write back.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _l3_catalog import COMM_L3, MATH_L3  # noqa: E402

DATA = os.path.join(ROOT, "data")
MATH_PATH = os.path.join(DATA, "syllabus_math.json")
COMM_PATH = os.path.join(DATA, "syllabus_comm.json")

MIN_TOTAL = 120
MAX_TOTAL = 180


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _fill_one(path: str, subject: str, catalog: dict[str, list[dict]]) -> tuple[int, list[str]]:
    syl = _load(path)
    kps = syl.get("kps") or {}
    errors: list[str] = []

    missing = [name for name in catalog if name not in kps]
    if missing:
        errors.append(f"{subject}: catalog keys missing in syllabus: {missing}")

    uncovered = [name for name in kps if name not in catalog]
    if uncovered:
        errors.append(f"{subject}: L2 without catalog: {uncovered}")

    total = 0
    for l2, meta in kps.items():
        if not isinstance(meta, dict):
            errors.append(f"{subject}: bad meta for {l2!r}")
            continue
        entries = catalog.get(l2)
        if not entries:
            errors.append(f"{subject}: empty l3 for {l2!r}")
            continue
        meta["l3"] = entries
        total += len(entries)

    if not (MIN_TOTAL <= total <= MAX_TOTAL):
        errors.append(f"{subject}: total L3={total} not in [{MIN_TOTAL},{MAX_TOTAL}]")

    if not errors:
        _dump(path, syl)
    return total, errors


def _validate_global() -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for subject, catalog in (("math", MATH_L3), ("comm", COMM_L3)):
        for l2, entries in catalog.items():
            if not entries:
                errors.append(f"{subject}/{l2}: empty l3 list")
            for e in entries:
                eid = e.get("id")
                if not eid or not isinstance(eid, str):
                    errors.append(f"{subject}/{l2}: missing id")
                    continue
                if eid in seen:
                    errors.append(f"duplicate id {eid}: {seen[eid]} vs {subject}/{l2}")
                else:
                    seen[eid] = f"{subject}/{l2}"
                rq = e.get("rag_queries") or []
                if not rq:
                    errors.append(f"{eid}: rag_queries empty")
                if not e.get("name"):
                    errors.append(f"{eid}: missing name")
                if "aliases" not in e or not isinstance(e["aliases"], list):
                    errors.append(f"{eid}: aliases must be list")
                allow = e.get("source_allow")
                if not isinstance(allow, list) or not allow:
                    errors.append(f"{eid}: source_allow must be non-empty list")
                # id prefix check
                parts = eid.split(".")
                if len(parts) < 3 or parts[0] not in ("math", "comm"):
                    errors.append(f"{eid}: id must be {{subject}}.{{l1}}.{{slug}}")
    return errors


def main() -> int:
    gerr = _validate_global()
    if gerr:
        print("GLOBAL VALIDATION FAILED:")
        for e in gerr:
            print(" ", e)
        return 1

    math_n, math_err = _fill_one(MATH_PATH, "math", MATH_L3)
    comm_n, comm_err = _fill_one(COMM_PATH, "comm", COMM_L3)
    errors = math_err + comm_err
    if errors:
        print("FILL FAILED:")
        for e in errors:
            print(" ", e)
        return 1

    # per-L2 counts
    print(f"math_l3_count={math_n}  (L2={len(MATH_L3)})")
    print(f"comm_l3_count={comm_n}  (L2={len(COMM_L3)})")
    print(f"unique_ids={math_n + comm_n}")
    for subject, catalog in (("math", MATH_L3), ("comm", COMM_L3)):
        unusual = [(k, len(v)) for k, v in catalog.items() if len(v) < 4 or len(v) > 6]
        if unusual:
            print(f"unusual counts ({subject}):")
            for k, n in unusual:
                print(f"  {k}: {n}")
    print("OK: syllabi written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
