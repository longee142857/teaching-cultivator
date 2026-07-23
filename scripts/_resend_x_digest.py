"""Resend tonight's archived x-digest to DingTalk."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from config import DATA_DIR, DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET
from deliver.dingtalk_bot import DingTalkBot
from deliver.x_digest import DigestItem, XDigest


def main() -> int:
    arch = Path(DATA_DIR) / "x_digest" / "archive"
    files = sorted(arch.glob("2026-07-15_21*.json"))
    if not files:
        files = sorted(arch.glob("2026-07-15_*.json"))
    if not files:
        print("no archive")
        return 1
    path = files[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [
        DigestItem(
            category=it.get("category", "ai"),
            title=it.get("title", ""),
            summary=it.get("summary", ""),
            source_url=it.get("source_url", ""),
            why_matters=it.get("why_matters", ""),
        )
        for it in (data.get("items") or [])
    ]
    text = data.get("text") or XDigest().format(items)
    print("archive", path.name, "chars", len(text), "items", len(items))

    bot = DingTalkBot(DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET)
    bot.set_cid_file(os.path.join(DATA_DIR, "conversation_id.json"))
    header = "## 补发：今日 21:00 X 资讯双周报\n\n"
    ok = bot.send_push(header + text)
    print("resend_ok", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
