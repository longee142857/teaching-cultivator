"""迁移 answer-log：自由 KP → 考纲 L2，并按 L2 重放 BKT 掌握度。

用法（云端）:
  cd /home/ubuntu/teaching-cultivator
  ./venv/bin/python scripts/migrate_answer_log_l2.py
  ./venv/bin/python scripts/migrate_answer_log_l2.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 与 main 一致：能 import bkt
try:
    import config  # noqa: F401 — 注入 knowledge-system/lib
except Exception:
    pass

from bkt import KCState
from learner.kp_registry import normalize_kp_for_grade, resolve_kp, reload_registry

LOG_PATH = os.path.join(ROOT, "data", "answer-log.jsonl")


def _guess_subject(raw_kp: str, entry: dict) -> str:
    subj = (entry.get("subject") or "").strip()
    if subj in ("math", "comm"):
        return subj
    if subj == "review":
        return "math"
    if resolve_kp("comm", raw_kp) and not resolve_kp("math", raw_kp):
        return "comm"
    if resolve_kp("math", raw_kp):
        return "math"
    if resolve_kp("comm", raw_kp):
        return "comm"
    return "math"


def migrate(dry_run: bool = False) -> int:
    reload_registry()
    if not os.path.isfile(LOG_PATH):
        print("no answer-log, skip")
        return 0

    rows = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    states: dict[str, KCState] = {}
    out_rows = []
    changed = 0

    for e in rows:
        raw = (e.get("knowledge_point") or "").strip()
        subj = _guess_subject(raw, e)
        new_kp = normalize_kp_for_grade(subj, raw) or raw or "未分类"
        if new_kp != raw:
            changed += 1

        correct = bool(e.get("correct"))
        kc = states.get(new_kp) or KCState(p_mastery=0.2)
        before = kc.p_mastery
        kc.update(correct)
        states[new_kp] = kc

        new_e = dict(e)
        new_e["knowledge_point"] = new_kp
        new_e["subject"] = subj
        new_e["knowledge_point_raw"] = raw
        new_e["mastery_before"] = round(before, 4)
        new_e["mastery_after"] = round(kc.p_mastery, 4)
        new_e["state"] = kc.to_dict()
        out_rows.append(new_e)

        print(
            "%s  %s → %s  correct=%s  %.3f→%.3f"
            % (
                (e.get("ts") or "")[:19],
                raw[:32],
                new_kp,
                correct,
                before,
                kc.p_mastery,
            )
        )

    print("---")
    print("entries=%d renamed=%d unique_l2=%d" % (len(out_rows), changed, len(states)))
    for kp, kc in sorted(states.items(), key=lambda x: x[1].p_mastery):
        print(
            "  L2 %-20s mastery=%.1f%% n=%d"
            % (kp, kc.p_mastery * 100, kc.opportunity_count)
        )

    if dry_run:
        print("dry-run: not written")
        return changed

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bak = LOG_PATH + ".bak." + ts
    shutil.copy2(LOG_PATH, bak)
    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in out_rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, LOG_PATH)
    print("wrote", LOG_PATH)
    print("backup", bak)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
