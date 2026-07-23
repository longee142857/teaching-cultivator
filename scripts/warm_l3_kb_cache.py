"""预热 kb_cache：全部 L2 + syllabus 中已声明的 L3（011-rag E2-B）。

用法:
  py -3 scripts/warm_l3_kb_cache.py
  py -3 scripts/warm_l3_kb_cache.py --cloud   # 预热后 scp store 需另跑 sync 或本脚本 --push-cloud
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.chdir(ROOT)


def iter_units(subject: str) -> list[tuple[str, list[str], list[str]]]:
    """[(unit_id, queries, source_allow), ...]"""
    from learner.kp_registry import load_syllabus

    syl = load_syllabus(subject)
    out: list[tuple[str, list[str], list[str]]] = []
    for l2, meta in (syl.get("kps") or {}).items():
        if not isinstance(meta, dict):
            continue
        # L2 unit
        from learner.rag_retrieve import resolve_unit_queries

        q, allow = resolve_unit_queries(subject, l2)
        out.append((l2, q, allow))
        for l3 in meta.get("l3") or []:
            if isinstance(l3, dict) and l3.get("id"):
                q3, a3 = resolve_unit_queries(subject, l3["id"])
                out.append((l3["id"], q3, a3))
    return out


def warm_one(subject: str, unit_id: str, queries: list[str], allow: list[str], top_k: int = 4) -> dict:
    from learner.rag_retrieve import rag_retrieve

    # 强制走 chroma（忽略空 cache）
    from learner import kb_cache

    # 若已有足够片段可跳过
    entry = kb_cache.peek(subject, unit_id)
    if entry and len(entry.get("snippets") or []) >= 2:
        return {"unit": unit_id, "status": "skip_cached", "n": len(entry["snippets"])}

    r = rag_retrieve(
        subject,
        unit_id,
        top_k=top_k,
        N=2,
        allow_local_chroma=True,
    )
    return {
        "unit": unit_id,
        "status": "ok" if r.ok else "fail",
        "n": r.hit_count,
        "backend": r.backend,
        "reason": r.reason,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", choices=["math", "comm", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="0=all")
    args = ap.parse_args()

    subjects = ["math", "comm"] if args.subject == "all" else [args.subject]
    report = {"ok": 0, "fail": 0, "skip": 0, "rows": []}
    for subj in subjects:
        units = iter_units(subj)
        if args.limit:
            units = units[: args.limit]
        print(f"=== {subj}: {len(units)} units ===")
        for unit_id, queries, allow in units:
            row = warm_one(subj, unit_id, queries, allow)
            report["rows"].append({"subject": subj, **row})
            st = row["status"]
            if st == "ok":
                report["ok"] += 1
            elif st == "skip_cached":
                report["skip"] += 1
            else:
                report["fail"] += 1
            print(f"  [{row['status']}] {unit_id} n={row['n']} {row.get('reason','')}")

    out = os.path.join(ROOT, "data", "kb_cache", "warm_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    total = report["ok"] + report["fail"] + report["skip"]
    hitish = report["ok"] + report["skip"]
    rate = hitish / total if total else 0
    print(f"DONE ok={report['ok']} skip={report['skip']} fail={report['fail']} coverage≈{rate:.1%}")
    print("report", out)
    # Gate: sample L3 must be ok or skip
    need = {"math.calc.limit.equiv", "comm.coding.hamming.code"}
    rows_by = {r["unit"]: r for r in report["rows"]}
    for u in need:
        r = rows_by.get(u)
        if not r or r["status"] == "fail":
            print("FAIL required unit", u, r)
            return 1
    return 0 if report["fail"] < max(3, total // 5) else 1


if __name__ == "__main__":
    raise SystemExit(main())
