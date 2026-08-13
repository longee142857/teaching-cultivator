# -*- coding: utf-8 -*-
"""One-shot: force a review push using running DingTalk credentials (no Stream)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DATA_DIR, DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET
from main import TeachingBot


def main() -> int:
    bot = TeachingBot(DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET)
    cid_path = os.path.join(DATA_DIR, "conversation_id.json")
    bot.dingtalk.set_cid_file(cid_path)
    print("[force] pushing review …", flush=True)
    bot.push_cultivate("review")
    print("[force] done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
