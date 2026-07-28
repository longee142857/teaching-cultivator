"""学员花名册：staffId → 目录与报名状态。"""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Optional

from learner import paths as P
from learner.context import LearnerIdentityError


def _load_index() -> dict[str, Any]:
    path = P.roster_index_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("learners"), dict):
                return data
    except Exception:
        pass
    return {"learners": {}, "updated_at": 0.0}


def _save_index(data: dict[str, Any]) -> None:
    os.makedirs(P.learners_root(), exist_ok=True)
    data["updated_at"] = time.time()
    path = P.roster_index_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def resolve_learner(staff_id: str) -> Optional[dict[str, Any]]:
    sid = (staff_id or "").strip()
    if not sid:
        return None
    return _load_index()["learners"].get(sid)


def list_learners() -> dict[str, dict[str, Any]]:
    return dict(_load_index().get("learners") or {})


def upsert_roster(
    staff_id: str,
    *,
    nick: str = "",
    source: str = "",
    status: str = "active",
) -> dict[str, Any]:
    sid = (staff_id or "").strip()
    if not sid:
        raise LearnerIdentityError("staff_id 为空，无法写入花名册")
    data = _load_index()
    prev = data["learners"].get(sid) or {}
    entry = {
        "staff_id": sid,
        "safe_id": P.safe_learner_id(sid),
        "nick": (nick or "").strip() or prev.get("nick") or "",
        "source": source or prev.get("source") or "",
        "status": status or prev.get("status") or "active",
        "enrolled_at": prev.get("enrolled_at") or time.time(),
        "updated_at": time.time(),
    }
    data["learners"][sid] = entry
    _save_index(data)
    return entry


def ensure_learner(
    staff_id: str,
    *,
    nick: str = "",
    source: str = "enroll",
) -> dict[str, Any]:
    """报名/首次见到：建目录 + 初始 weights + 花名册。"""
    sid = (staff_id or "").strip()
    if not sid:
        raise LearnerIdentityError("staff_id 为空，禁止 ensure_learner")
    d = P.ensure_learner_dir(sid)
    wpath = P.weights_path(sid)
    if not os.path.isfile(wpath):
        example = P.weights_example_path()
        if os.path.isfile(example):
            shutil.copy2(example, wpath)
        else:
            with open(wpath, "w", encoding="utf-8") as f:
                json.dump({"math": {"kps": {}}, "comm": {"kps": {}}}, f, ensure_ascii=False, indent=2)
    # 空 answer-log 可惰性创建
    return upsert_roster(sid, nick=nick, source=source, status="active")


ENROLL_PHRASES = (
    "报名培养",
    "我要报名",
    "加入培养",
    "enroll",
)


def is_enroll_utterance(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    for p in ENROLL_PHRASES:
        if p.lower() in t:
            return True
    return False
