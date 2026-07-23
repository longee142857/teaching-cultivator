"""云端：应用本机回填的 fulfillments JSON/JSONL。

用法:
  python scripts/kb_cache_apply.py /tmp/fulfillments.jsonl
"""
from __future__ import annotations

import json
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.kb_cache import apply_fulfillments  # noqa: E402


def load_items(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read().strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(json.loads(line))
    return items


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: kb_cache_apply.py <fulfillments.jsonl>", file=sys.stderr)
        return 2
    items = load_items(sys.argv[1])
    r = apply_fulfillments(items)
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
