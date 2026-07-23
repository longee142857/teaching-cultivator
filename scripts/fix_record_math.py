"""One-off: normalize math delimiters in monthly record files."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from math_format import normalize_math_delimiters

record_dir = ROOT / "data" / "daily_records"
for md in sorted(record_dir.glob("????-??.md")):
    text = md.read_text(encoding="utf-8")
    fixed = normalize_math_delimiters(text)
    fixed = re.sub(r"---##", "---\n\n##", fixed)
    if fixed != text:
        md.write_text(fixed, encoding="utf-8")
        print(f"fixed {md.name}")
    else:
        print(f"ok {md.name}")
