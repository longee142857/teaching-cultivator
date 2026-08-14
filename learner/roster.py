"""学员花名册：staffId → 目录与报名状态。

静默策略（方案 A）：
- 开户后超过 SILENT_AFTER_SEC 未作答（无 last_answer_at 更新）→ status=silent
- 保留 id 与目录；隔绝学习态写入（weights / answer-log 副作用 / 公共课同步进个人 memory 等）
- 任意真实作答（grade 写日志）→ mark_answered 唤醒为 active
- 纯私聊不唤醒；schedule 绑定不受静默闸影响
"""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Optional

from learner import paths as P
from learner.context import LearnerIdentityError

STATUS_ACTIVE = "active"
STATUS_SILENT = "silent"

# 超过此时长未作答 → 静默（可用环境变量覆盖，单位秒）
def _silent_after_sec() -> float:
    try:
        raw = os.environ.get("SILENT_AFTER_SEC", "").strip()
        if raw:
            return max(60.0, float(raw))
    except Exception:
        pass
    return 24 * 3600.0


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


def list_active_learners() -> dict[str, dict[str, Any]]:
    """刷新静默后仅返回 active。"""
    out: dict[str, dict[str, Any]] = {}
    for sid in list(list_learners().keys()):
        entry = refresh_silent_status(sid)
        if entry and entry.get("status") == STATUS_ACTIVE:
            out[sid] = entry
    return out


def normalize_exam_code(code: str) -> str:
    """H5 编号：'01' 与 '1' 视为同一码。非纯数字原样返回。"""
    s = (code or "").strip()
    if s.isdigit():
        return str(int(s))
    return s


def resolve_exam_uid(raw: str) -> str:
    """H5 短编号 → 花名册 staff_id。

    钉钉 staffId（长数字）原样返回。1–8 位编号按 exam_code 匹配；
    未登记时，'1'/'01' 回落到 OWNER_STAFF_ID（当前单人主学员）。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    learners = list_learners()
    # 长 staffId 已在花名册 → 直接用；短数字编号即使误入花名册也继续按 exam_code 解析
    if raw in learners and not (raw.isdigit() and len(raw) <= 8):
        return raw
    key = normalize_exam_code(raw)
    for sid, entry in learners.items():
        if not isinstance(entry, dict):
            continue
        if sid.isdigit() and len(sid) <= 8:
            continue
        code = entry.get("exam_code") or ""
        if code and normalize_exam_code(str(code)) == key:
            return sid
    if raw.isdigit() and 1 <= len(raw) <= 8:
        try:
            from learner.context import owner_staff_id
            owner = owner_staff_id()
        except Exception:
            owner = ""
        if owner:
            oe = learners.get(owner) or {}
            oc = str(oe.get("exam_code") or "01")
            if normalize_exam_code(oc) == key:
                return owner
    if raw in learners:
        return raw
    return raw


def upsert_roster(
    staff_id: str,
    *,
    nick: str = "",
    source: str = "",
    status: Optional[str] = None,
    last_answer_at: Optional[float] = None,
    set_last_answer_at: bool = False,
    exam_code: Optional[str] = None,
) -> dict[str, Any]:
    """写入/更新花名册。

    status / last_answer_at 默认保留旧值（避免私聊 save_discuss_user 误把 silent 刷回 active）。
    set_last_answer_at=True 时写入 last_answer_at（缺省 now）并强制 active。
    """
    sid = (staff_id or "").strip()
    if not sid:
        raise LearnerIdentityError("staff_id 为空，无法写入花名册")
    data = _load_index()
    prev = data["learners"].get(sid) or {}
    now = time.time()

    if set_last_answer_at:
        ans_ts = float(last_answer_at) if last_answer_at is not None else now
        new_status = STATUS_ACTIVE
    else:
        ans_ts = prev.get("last_answer_at")
        if last_answer_at is not None:
            ans_ts = float(last_answer_at)
        if status is not None:
            new_status = status
        else:
            new_status = prev.get("status") or STATUS_ACTIVE

    entry = {
        "staff_id": sid,
        "safe_id": P.safe_learner_id(sid),
        "nick": (nick or "").strip() or prev.get("nick") or "",
        "source": source or prev.get("source") or "",
        "status": new_status,
        "enrolled_at": prev.get("enrolled_at") or now,
        "last_answer_at": ans_ts,
        "exam_code": str(
            exam_code if exam_code is not None else prev.get("exam_code") or ""
        ).strip(),
        "updated_at": now,
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
    """报名/首次见到：建目录 + 初始 weights + 花名册。

    口令报名显式 active；已存在学员保留原 status（含 silent）。
    """
    sid = (staff_id or "").strip()
    if not sid:
        raise LearnerIdentityError("staff_id 为空，禁止 ensure_learner")
    P.ensure_learner_dir(sid)
    wpath = P.weights_path(sid)
    if not os.path.isfile(wpath):
        example = P.weights_example_path()
        if os.path.isfile(example):
            shutil.copy2(example, wpath)
        else:
            with open(wpath, "w", encoding="utf-8") as f:
                json.dump({"math": {"kps": {}}, "comm": {"kps": {}}}, f, ensure_ascii=False, indent=2)

    prev = resolve_learner(sid)
    if source == "enroll":
        return upsert_roster(sid, nick=nick, source=source, status=STATUS_ACTIVE)
    if prev:
        return upsert_roster(sid, nick=nick, source=source)
    return upsert_roster(sid, nick=nick, source=source, status=STATUS_ACTIVE)


def _answer_anchor(entry: dict[str, Any]) -> float:
    """未作答过则用 enrolled_at 起算。"""
    la = entry.get("last_answer_at")
    if isinstance(la, (int, float)) and la > 0:
        return float(la)
    en = entry.get("enrolled_at")
    if isinstance(en, (int, float)) and en > 0:
        return float(en)
    return 0.0


def _infer_last_answer_from_log(staff_id: str) -> Optional[float]:
    """从 answer-log 推断最近作答时间（兼容升级前无 last_answer_at 的花名册）。"""
    try:
        path = P.answer_log_path(staff_id)
    except Exception:
        return None
    if not os.path.isfile(path):
        return None
    latest: Optional[float] = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("status") == "audit" and e.get("correct") is None:
                    continue
                raw = e.get("ts")
                if not raw:
                    continue
                try:
                    from datetime import datetime

                    t = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if latest is None or t > latest:
                    latest = t
    except OSError:
        return None
    return latest


def refresh_silent_status(staff_id: str, *, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """按方案 A 刷新 status；返回最新条目（不存在则 None）。"""
    sid = (staff_id or "").strip()
    if not sid:
        return None
    data = _load_index()
    entry = data["learners"].get(sid)
    if not entry:
        return None
    ts = float(now if now is not None else time.time())

    # 升级兼容：缺 last_answer_at 时从 answer-log 回填一次
    la = entry.get("last_answer_at")
    if not (isinstance(la, (int, float)) and la > 0):
        inferred = _infer_last_answer_from_log(sid)
        if inferred is not None:
            entry = {**entry, "last_answer_at": inferred, "updated_at": ts}
            data["learners"][sid] = entry
            _save_index(data)

    anchor = _answer_anchor(entry)
    limit = _silent_after_sec()
    cur = entry.get("status") or STATUS_ACTIVE

    if anchor > 0 and (ts - anchor) >= limit:
        if cur != STATUS_SILENT:
            entry = {**entry, "status": STATUS_SILENT, "updated_at": ts}
            data["learners"][sid] = entry
            _save_index(data)
        return data["learners"][sid]

    # 锚点仍在窗口内：若曾被标 silent 但 last_answer 已更新，拉回 active
    if cur == STATUS_SILENT and anchor > 0 and (ts - anchor) < limit:
        entry = {**entry, "status": STATUS_ACTIVE, "updated_at": ts}
        data["learners"][sid] = entry
        _save_index(data)
        return data["learners"][sid]

    return entry


def sweep_silent(*, now: Optional[float] = None) -> list[str]:
    """扫描全员，返回新进入 silent 的 staff_id 列表。"""
    flipped: list[str] = []
    for sid, prev in list_learners().items():
        before = prev.get("status")
        after = refresh_silent_status(sid, now=now)
        if after and before != STATUS_SILENT and after.get("status") == STATUS_SILENT:
            flipped.append(sid)
    return flipped


def mark_answered(staff_id: str | None = None, *, at: Optional[float] = None) -> Optional[dict[str, Any]]:
    """作答唤醒：刷新 last_answer_at 并置 active。"""
    sid = (staff_id or "").strip()
    if not sid:
        try:
            from learner.context import get_learner_id

            sid = (get_learner_id() or "").strip()
        except Exception:
            sid = ""
    if not sid:
        return None
    # 确保花名册有条目
    if resolve_learner(sid) is None:
        ensure_learner(sid, source="answer")
    return upsert_roster(sid, set_last_answer_at=True, last_answer_at=at)


def is_silent(staff_id: str | None = None) -> bool:
    sid = (staff_id or "").strip()
    if not sid:
        try:
            from learner.context import get_learner_id

            sid = (get_learner_id() or "").strip()
        except Exception:
            return False
    if not sid:
        return False
    entry = refresh_silent_status(sid)
    return bool(entry and entry.get("status") == STATUS_SILENT)


def allows_learning_writes(staff_id: str | None = None) -> bool:
    """学习态写入是否允许。

    schedule 绑定（公共课/课表）始终允许；silent 个人账户拒绝。
    无身份上下文时放行（兼容单测与无花名册路径）。
    """
    try:
        from learner.context import get_binding, get_learner_id

        if get_binding() == "schedule":
            return True
        sid = (staff_id or get_learner_id() or "").strip()
    except Exception:
        sid = (staff_id or "").strip()
    if not sid:
        return True
    if resolve_learner(sid) is None:
        return True
    return not is_silent(sid)


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
