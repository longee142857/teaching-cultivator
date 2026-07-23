"""钉钉讨论用户（单聊 userId / staffId）持久化。"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from config import DATA_DIR

USERS_PATH = os.path.join(DATA_DIR, "dingtalk_discuss_user.json")


def load_discuss_user() -> dict[str, Any]:
    try:
        if os.path.isfile(USERS_PATH):
            with open(USERS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("user_id"):
                return data
    except Exception:
        pass
    return {}


def save_discuss_user(
    user_id: str,
    *,
    nick: str = "",
    source: str = "",
) -> None:
    uid = (user_id or "").strip()
    if not uid:
        return
    payload = {
        "user_id": uid,
        "nick": (nick or "").strip(),
        "source": source,
        "updated_at": time.time(),
    }
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = USERS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, USERS_PATH)
    except Exception:
        pass


def get_discuss_user_id() -> str:
    return (load_discuss_user().get("user_id") or "").strip()
