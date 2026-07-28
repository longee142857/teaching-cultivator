"""钉钉讨论用户 — 写入学员花名册（不再覆盖 singleton）。"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from config import DATA_DIR, OWNER_STAFF_ID

USERS_PATH = os.path.join(DATA_DIR, "dingtalk_discuss_user.json")


def load_discuss_user() -> dict[str, Any]:
    """读取 legacy 单用户文件（迁移/兼容）。"""
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
    try:
        from learner.roster import upsert_roster

        upsert_roster(uid, nick=nick, source=source or "dingtalk")
    except Exception:
        pass


def get_discuss_user_id() -> str:
    """Deprecated：owner 提示。优先 OWNER_STAFF_ID，其次 legacy 文件。"""
    owner = (OWNER_STAFF_ID or "").strip()
    if owner:
        return owner
    return (load_discuss_user().get("user_id") or "").strip()
