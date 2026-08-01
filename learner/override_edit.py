"""批改纠正提案 — agent 只能登记覆盖提案，用户确认卡片后才重算 mastery。

复用 kp_edit 的「提案 → 确认卡 → 正则直连落盘」模式，防止 LLM 一念之间改 BKT。
- 任何覆盖写 answer-log 都必须先 propose → confirm；未确认一律不写。
- 确认卡按钮 dtmd 回传文案须与 agent._OVERRIDE_CONFIRM_RE 匹配。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from config import DATA_DIR

PROPOSALS_PATH = os.path.join(DATA_DIR, "override_proposals.json")
AUDIT_PATH = os.path.join(DATA_DIR, "override_edit_audit.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str, default: dict) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _audit(kind: str, **fields) -> None:
    os.makedirs(os.path.dirname(AUDIT_PATH) or ".", exist_ok=True)
    row = {"ts": _now_iso(), "kind": kind, **fields}
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_proposals() -> dict:
    return _load_json(PROPOSALS_PATH, {"proposals": []})


def _staff_of(token: str) -> dict | None:
    for p in _load_proposals().get("proposals", []):
        if p.get("token") == token:
            return p
    return None


def propose_override(
    kp: str,
    correct: bool,
    subject: str = "",
    credit: float = 0.0,
    *,
    staff_id: str = "",
) -> dict:
    """登记一个待确认的批改纠正提案；不写 answer-log。"""
    kp = (kp or "").strip()
    if not kp:
        return {"ok": False, "error": "缺少知识点名"}
    if not isinstance(correct, bool):
        return {"ok": False, "error": "correct 必须是布尔值"}

    token = uuid.uuid4().hex[:12]
    props = _load_proposals()
    # 同 kp 已有 pending 提案 → 去重，避免重复发卡
    for p in props.get("proposals", []):
        if p.get("status") == "pending" and p.get("kp") == kp:
            return {
                "ok": False,
                "error": f"「{kp}」已有待确认的纠正提案，请先处理旧卡片",
                "token": p.get("token"),
            }
    props.setdefault("proposals", []).append({
        "token": token,
        "kp": kp,
        "correct": bool(correct),
        "subject": (subject or "").strip(),
        "credit": float(credit) if credit else None,
        "staff_id": (staff_id or "").strip(),
        "ts": _now_iso(),
        "status": "pending",
    })
    _save_json(PROPOSALS_PATH, props)
    _audit("propose", token=token, kp=kp, correct=bool(correct),
           subject=(subject or "").strip())
    return {"ok": True, "token": token, "kp": kp, "correct": bool(correct),
            "subject": (subject or "").strip()}


def confirm_override(token: str, *, staff_id: str = "") -> dict:
    """确认提案 → 真正覆盖 mastery。返回执行结果。"""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "缺少确认 token"}
    target = _staff_of(token)
    if not target:
        return {"ok": False, "error": f"找不到纠正提案 {token}（可能已过期或被取消）"}
    if target.get("status") != "pending":
        return {"ok": False, "error": f"提案已处理（status={target.get('status')}），请勿重复确认"}
    sid = (staff_id or "").strip()
    if sid and target.get("staff_id") and sid != target.get("staff_id"):
        return {"ok": False, "error": "该提案不是你提出的，无法确认"}

    # 标记前先真正执行覆盖（answer-log 追加 overridden 记录）
    from agent.tools import override_grade
    msg = override_grade(
        target.get("kp", ""),
        bool(target.get("correct", False)),
        subject=target.get("subject", ""),
        credit=float(target.get("credit") or 0.0),
    )

    target["status"] = "confirmed"
    target["confirmed_at"] = _now_iso()
    _save_json(PROPOSALS_PATH, _load_proposals())
    _audit("confirm", token=token, kp=target.get("kp", ""), result=msg)
    return {"ok": True, "kp": target.get("kp", ""), "msg": msg}


def cancel_override(token: str, *, staff_id: str = "") -> dict:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "缺少取消 token"}
    target = _staff_of(token)
    if not target:
        return {"ok": False, "error": f"找不到纠正提案 {token}（可能已过期）"}
    if target.get("status") != "pending":
        return {"ok": False, "error": f"提案已处理（status={target.get('status')}）"}
    sid = (staff_id or "").strip()
    if sid and target.get("staff_id") and sid != target.get("staff_id"):
        return {"ok": False, "error": "该提案不是你提出的，无法取消"}
    target["status"] = "cancelled"
    target["cancelled_at"] = _now_iso()
    _save_json(PROPOSALS_PATH, _load_proposals())
    _audit("cancel", token=token, kp=target.get("kp", ""))
    return {"ok": True, "kp": target.get("kp", "")}
