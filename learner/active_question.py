"""当前题单一真相源 — 合并个人 last_push 与公共 last_class，取 timestamp 最新。

背景（mg#1）：定时公共推送写 public/last_class；私聊自出题写个人 last_push。
历史上 memory_blocks.refresh_from_last_push 固定读个人 last_push，导致公共推送后
对话记忆仍停在旧个人题 →「这一轮当前题不清楚」。
本模块统一取两者最新，作为白名单读 get_active_question 与 memory 刷新的唯一依据。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from learner import paths as P


def _read_json(path: str) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _ts_of(d: dict) -> Optional[datetime]:
    raw = (d.get("timestamp") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return None


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else -1
    except OSError:
        return -1


def latest_push_record(staff_id: str = "") -> dict:
    """个人 last_push 与公共 last_class 中 timestamp 最新的那条。"""
    candidates = []
    paths = []
    try:
        paths.append(("last_push", P.last_push_path(staff_id)))
    except Exception:
        pass
    paths.append(("public_class", P.public_last_class_path()))

    for source, path in paths:
        data = _read_json(path)
        if data:
            data["_source"] = source
            data["_mtime"] = _mtime(path)
            candidates.append(data)

    if not candidates:
        return {}
    if len(candidates) == 1:
        return candidates[0]

    # 优先比较 timestamp；缺失时回退 mtime
    ts_list = [(i, _ts_of(d)) for i, d in enumerate(candidates)]
    if all(t is not None for _, t in ts_list):
        return candidates[max(ts_list, key=lambda x: x[1])[0]]
    return candidates[0] if candidates[0]["_mtime"] >= candidates[1]["_mtime"] else candidates[1]


def get_active_question(staff_id: str = "") -> dict:
    """返回当前题完整信息（白名单读）。字段对齐 tools.py 的 _load_last_push_record。"""
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
        "timestamp": str(rec.get("timestamp") or ""),
        "source": str(rec.get("_source") or ""),
        "preview": q[:200],
        "question": q,
    }
