"""One-shot: check answer-log → BKT/weights落地 on cloud."""
from __future__ import annotations
import json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from learner.kp_registry import resolve_kp

try:
    from bkt import BKTLogger
except ImportError:
    # some deploys nest under lib/
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from bkt import BKTLogger

print("=== answer-log raw ===")
rows = []
with open("data/answer-log.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
print("entries", len(rows), "unique_raw_kp", len({r.get("knowledge_point") for r in rows}))
for r in rows:
    print(
        r["ts"][:19],
        "correct=" + str(r.get("correct")),
        "before=%.3f" % (r.get("mastery_before") or 0),
        "after=%.3f" % (r.get("mastery_after") or 0),
        "|",
        (r.get("knowledge_point") or "")[:50],
    )

print("\n=== live BKT mastery map ===")
bkt = BKTLogger(os.path.join("data", "answer-log.jsonl"))
all_m = bkt.get_all_kp_mastery("wx_123") or {}
print("keys", len(all_m))
for k, v in sorted(all_m.items(), key=lambda x: x[1]):
    print("  %.1f%% | %s" % (v * 100, (k or "")[:60]))

print("\n=== re-resolve historical → L2 ===")
buckets = defaultdict(list)
for e in rows:
    raw = e.get("knowledge_point") or ""
    resolved = None
    for subj in ("math", "comm"):
        resolved = resolve_kp(subj, raw)
        if resolved:
            break
    key = resolved or ("UNRESOLVED:" + raw[:40])
    buckets[key].append(
        (e["ts"][:19], e.get("correct"), e.get("mastery_after"), raw[:40])
    )
for k, items in sorted(buckets.items(), key=lambda x: -len(x[1])):
    print("L2=%s n=%d" % (k, len(items)))
    for it in items:
        print(" ", it)

print("\n=== weights TOP (math) ===")
w = json.load(open("data/weights.json", encoding="utf-8"))
math_w = (w.get("math") or {}).get("kp_weights") or {}
top = sorted(math_w.items(), key=lambda x: -x[1])[:8]
for k, v in top:
    print(" ", round(v, 4), k)
print("weights mtime", os.path.getmtime("data/weights.json"))
print("difficulty exists", os.path.isfile("data/difficulty.json"))

print("\n=== last grade in transcript? ===")
tp = "data/agent_transcript.json"
if os.path.isfile(tp):
    d = json.load(open(tp, encoding="utf-8"))
    for m in d.get("messages") or []:
        if m.get("role") == "tool" and "正确" in (m.get("content") or ""):
            print((m.get("content") or "")[:200])
            break
