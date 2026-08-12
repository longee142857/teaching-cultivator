"""当前题单一真相源 — SQLite pushes 中该学员可见的最新一条。

BIG-TEACH-013：运行时读路径只走 teaching.db。
个人自出题（learner_id=学员）与公共课（learner_id IS NULL）共池，
取 pushed_at 最新；作为白名单读 get_active_question 与 memory 刷新的唯一依据。
"""
from __future__ import annotations

from typing import Optional

from learner import db as _store


def latest_push_record(staff_id: str = "") -> dict:
    """该学员可见 pushes 中 pushed_at 最新一条。"""
    from learner.db import get_store
    rec = get_store().get_latest_push(staff_id or "")
    return rec or {}


def get_active_question(staff_id: str = "") -> dict:
    """返回当前题完整信息（白名单读）。"""
    rec = latest_push_record(staff_id)
    if not rec:
        return {"found": False}
    q = (rec.get("question") or "").strip()
    if not q:
        return {"found": False}
    return {
        "found": True,
        "subject": str(rec.get("subject") or ""),
        "kp": str(rec.get("kp") or ""),
        "difficulty": str(rec.get("difficulty") or ""),
        "item_form": str(rec.get("item_form") or ""),
        "ability_goal": str(rec.get("ability_goal") or ""),
        "timestamp": str(rec.get("pushed_at") or rec.get("timestamp") or ""),
        "source": str(rec.get("_source") or "db"),
        "preview": q[:200],
        "question": q,
    }
