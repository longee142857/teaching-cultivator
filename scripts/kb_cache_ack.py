"""云端：批量 ack 队列 id。stdin JSON: {"ids":[...],"status":"failed","note":"..."}"""
from __future__ import annotations

import json
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.kb_cache import ack  # noqa: E402


def main() -> int:
    data = json.loads(sys.stdin.read() or "{}")
    n = ack(
        list(data.get("ids") or []),
        status=data.get("status") or "done",
        note=data.get("note") or "",
    )
    print(json.dumps({"acked": n}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
