"""学员/公共课路径解析。

共享只读：syllabus / kb_cache / bkt_overrides / weights.example
公共运维：public/last_class、push-retry-*
个人状态：data/learners/{safe_id}/
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import config as _cfg

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _data_dir() -> str:
    return _cfg.DATA_DIR


def teaching_db_path() -> str:
    """SQLite 真相源库路径（BIG-TEACH-013）。"""
    try:
        if (_cfg.TEACHING_DB or "").strip():
            return _cfg.TEACHING_DB.strip()
    except Exception:
        pass
    return os.path.join(_data_dir(), "teaching.db")


def safe_learner_id(staff_id: str) -> str:
    sid = (staff_id or "").strip()
    if not sid:
        raise ValueError("empty staff_id")
    # 钉钉 staffId 多为数字/字母；仍做路径消毒
    out = _SAFE_RE.sub("_", sid)
    if out in (".", "..") or not out:
        raise ValueError(f"unsafe staff_id: {staff_id!r}")
    return out


def learners_root() -> str:
    return os.path.join(_data_dir(), "learners")


def public_dir() -> str:
    return os.path.join(_data_dir(), "public")


def roster_index_path() -> str:
    return os.path.join(learners_root(), "index.json")


def learner_dir(staff_id: Optional[str] = None) -> str:
    from learner.context import current_user_id

    sid = (staff_id or "").strip() or current_user_id()
    return os.path.join(learners_root(), safe_learner_id(sid))


def ensure_learner_dir(staff_id: Optional[str] = None) -> str:
    d = learner_dir(staff_id)
    os.makedirs(d, exist_ok=True)
    return d


def _p(name: str, staff_id: Optional[str] = None) -> str:
    return os.path.join(learner_dir(staff_id), name)


def weights_path(staff_id: Optional[str] = None) -> str:
    return _p("weights.json", staff_id)


def answer_log_path(staff_id: Optional[str] = None) -> str:
    return _p("answer-log.jsonl", staff_id)


def last_push_path(staff_id: Optional[str] = None) -> str:
    """个人 last_push（私聊自出题）。"""
    return _p("last_push.json", staff_id)


def difficulty_path(staff_id: Optional[str] = None) -> str:
    return _p("difficulty.json", staff_id)


def memory_blocks_path(staff_id: Optional[str] = None) -> str:
    return _p("memory_blocks.json", staff_id)


def transcript_path(staff_id: Optional[str] = None) -> str:
    return _p("agent_transcript.json", staff_id)


def recent_kp_picks_path(staff_id: Optional[str] = None) -> str:
    return _p("recent_kp_picks.json", staff_id)


def recent_ability_path(staff_id: Optional[str] = None) -> str:
    return _p("recent_ability_picks.json", staff_id)


def refine_queue_path(staff_id: Optional[str] = None) -> str:
    return _p("refine-queue.jsonl", staff_id)


def refine_archive_dir(staff_id: Optional[str] = None) -> str:
    return os.path.join(learner_dir(staff_id), "refine-queue-archive")


def public_last_class_path() -> str:
    return os.path.join(public_dir(), "last_class.json")


def weights_example_path() -> str:
    return os.path.join(_data_dir(), "weights.example.json")


# 共享只读（根 data/）
def syllabus_path(subject: str) -> str:
    return os.path.join(_data_dir(), f"syllabus_{subject}.json")


def legacy_kp_map_path() -> str:
    return os.path.join(_data_dir(), "legacy_kp_map.json")


def parse_push_ts(raw: str):
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def last_push_file_stale(path: str, db_ts: str = "") -> bool:
    """True when last_push.json / last_class is older than the newest SQLite push."""
    db_dt = parse_push_ts(db_ts)
    if db_dt is None:
        return False
    file_dt = None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        file_dt = parse_push_ts(
            str((data or {}).get("timestamp") or (data or {}).get("pushed_at") or "")
        )
    except Exception:
        file_dt = None
    if file_dt is None:
        try:
            file_dt = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        except OSError:
            return True
    if db_dt.tzinfo and file_dt.tzinfo is None:
        file_dt = file_dt.replace(tzinfo=db_dt.tzinfo)
    if file_dt.tzinfo and db_dt.tzinfo is None:
        db_dt = db_dt.replace(tzinfo=file_dt.tzinfo)
    return file_dt < db_dt
