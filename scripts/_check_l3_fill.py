"""Gate check for BIG-TEACH-011b L3 fill.

Reloads syllabi via kp_registry, validates counts/uniqueness/resolve,
writes data/l3-fill-check.json (override with L3_FILL_CHECK_OUT).
"""
from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

OUT_PATH = os.environ.get(
    "L3_FILL_CHECK_OUT",
    os.path.join(ROOT, "data", "l3-fill-check.json"),
)
MIN_TOTAL = 120
MAX_TOTAL = 180


def main() -> int:
    from learner.kp_registry import load_syllabus, reload_registry
    from learner.rag_retrieve import resolve_unit_queries

    reload_registry()

    stats: dict = {
        "math_l3_count": 0,
        "comm_l3_count": 0,
        "unique_ids": 0,
        "l2_covered_math": 0,
        "l2_covered_comm": 0,
        "per_l2": {"math": {}, "comm": {}},
        "resolve_ok": 0,
        "resolve_fail": [],
        "errors": [],
    }
    all_ids: list[str] = []
    seen: set[str] = set()

    for subject in ("math", "comm"):
        syl = load_syllabus(subject)
        kps = syl.get("kps") or {}
        covered = 0
        total = 0
        for l2, meta in kps.items():
            if not isinstance(meta, dict):
                stats["errors"].append(f"{subject}/{l2}: bad meta")
                continue
            l3s = meta.get("l3") or []
            n = len(l3s) if isinstance(l3s, list) else 0
            stats["per_l2"][subject][l2] = n
            if n == 0:
                stats["errors"].append(f"{subject}/{l2}: empty l3")
                continue
            covered += 1
            total += n
            for e in l3s:
                if not isinstance(e, dict):
                    stats["errors"].append(f"{subject}/{l2}: bad l3 entry")
                    continue
                eid = e.get("id")
                if not eid:
                    stats["errors"].append(f"{subject}/{l2}: missing id")
                    continue
                if eid in seen:
                    stats["errors"].append(f"duplicate id: {eid}")
                seen.add(eid)
                all_ids.append(eid)
                rq = e.get("rag_queries") or []
                if not rq:
                    stats["errors"].append(f"{eid}: empty rag_queries")
        key = f"{subject}_l3_count"
        stats[key] = total
        stats[f"l2_covered_{subject}"] = covered
        if covered != 30:
            stats["errors"].append(f"{subject}: covered L2={covered}, expect 30")
        if not (MIN_TOTAL <= total <= MAX_TOTAL):
            stats["errors"].append(
                f"{subject}: total={total} not in [{MIN_TOTAL},{MAX_TOTAL}]"
            )

    stats["unique_ids"] = len(seen)
    if len(seen) != len(all_ids):
        stats["errors"].append(
            f"unique mismatch: unique={len(seen)} total={len(all_ids)}"
        )

    # resolve_unit_queries for 5 random L3 ids
    rng = random.Random(42)
    sample = rng.sample(all_ids, min(5, len(all_ids))) if all_ids else []
    for eid in sample:
        subject = "math" if eid.startswith("math.") else "comm"
        queries, allow = resolve_unit_queries(subject, eid)
        if queries and len(queries) >= 1:
            stats["resolve_ok"] += 1
        else:
            stats["resolve_fail"].append(eid)
            stats["errors"].append(f"resolve failed: {eid}")

    if sample and stats["resolve_ok"] < len(sample):
        stats["errors"].append(
            f"resolve_ok={stats['resolve_ok']} < sample={len(sample)}"
        )

    # unusual per-L2 counts
    unusual = []
    for subject in ("math", "comm"):
        for l2, n in stats["per_l2"][subject].items():
            if n < 4 or n > 6:
                unusual.append({"subject": subject, "l2": l2, "n": n})
    stats["unusual_counts"] = unusual

    passed = len(stats["errors"]) == 0
    report = {
        "PASS": passed,
        "math_l3_count": stats["math_l3_count"],
        "comm_l3_count": stats["comm_l3_count"],
        "unique_ids": stats["unique_ids"],
        "l2_covered_math": stats["l2_covered_math"],
        "l2_covered_comm": stats["l2_covered_comm"],
        "resolve_sample": sample,
        "resolve_ok": stats["resolve_ok"],
        "unusual_counts": unusual,
        "errors": stats["errors"],
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
