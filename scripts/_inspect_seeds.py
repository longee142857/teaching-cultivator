"""Inspect seed YAML / kb_cache vs today's L2 kps."""
from __future__ import annotations
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
math_dir = ROOT / "data" / "daily_records" / "structured" / "math"
comm_dir = ROOT / "data" / "daily_records" / "structured" / "comm"

print("comm dir", comm_dir, "exists", comm_dir.is_dir())
print("comm yaml", list(comm_dir.glob("*.yaml")) if comm_dir.is_dir() else [])

entries = []
for p in sorted(math_dir.glob("*.yaml")):
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        entries.extend(data)
print("math yaml entries", len(entries))
for e in entries:
    print(f"  {e.get('id')}: kp={e.get('kp')} diff={e.get('difficulty')} qlen={len(e.get('question') or '')}")

for target in ["矩阵与初等变换", "幂级数与函数展开", "循环码与CRC", "极限与连续"]:
    hit = [e for e in entries if target in (e.get("kp") or [])]
    soft = [
        e
        for e in entries
        if any(target in str(k) or str(k) in target for k in (e.get("kp") or []))
    ]
    print(f"exact '{target}': {len(hit)} soft:{len(soft)} ids={[e.get('id') for e in hit[:3]]}")

for eid in ["2018-math1-005", "2018-math1-006"]:
    e = next((x for x in entries if x.get("id") == eid), None)
    if not e:
        print("missing", eid)
        continue
    print("---", eid, "kp=", e.get("kp"))
    print((e.get("question") or "")[:240].replace("\n", " "))

store_path = ROOT / "data" / "kb_cache" / "store.json"
store = json.loads(store_path.read_text(encoding="utf-8"))
ents = store.get("entries") or {}
print("kb entries", len(ents))
for k, v in list(ents.items())[:30]:
    n = len((v or {}).get("snippets") or [])
    print(f"  {k}: snippets={n} hits={(v or {}).get('hits')}")
