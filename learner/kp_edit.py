"""知识点提案与最小写入 — agent 只能登记 L3 提案，用户确认卡片后才落盘。

安全边界（对应 CLAUDE.md）：
- 只允许追加 L3 子考点到**已存在**的 L2 章节下；绝不新建 L2（BKT 掌握度主键挂 L2）。
- l3_id 自动生成：取该 L2 现有 l3 的点分前缀，末段用 k{n} 递增，跨 L2 查重保证唯一。
- 任何写入都走提案 → 确认 → 审计；未确认一律不落盘。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from config import DATA_DIR

PROPOSALS_PATH = os.path.join(DATA_DIR, "kp_proposals.json")
AUDIT_PATH = os.path.join(DATA_DIR, "kp_edit_audit.jsonl")


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


def _syllabus_path(subject: str) -> str:
    from learner import kp_registry
    return kp_registry.SYLLABUS_PATHS.get(subject) or ""


def _gen_l3_id(subject: str, l2_name: str, all_ids: set[str]) -> str:
    """从该 L2 现有 l3 的点分前缀推导 id；无前缀退回 {subject}.kp。"""
    from learner import kp_registry
    prefix = ""
    for l3 in kp_registry.list_l3_for_l2(subject, l2_name):
        if isinstance(l3, dict):
            lid = (l3.get("id") or "").strip()
            if "." in lid:
                prefix = lid.rsplit(".", 1)[0]
                break
    if not prefix:
        prefix = f"{subject}.kp"
    n = 1
    while f"{prefix}.k{n}" in all_ids:
        n += 1
    return f"{prefix}.k{n}"


def _dedup_error(subject: str, l2_name: str, name: str, aliases: list[str]) -> str:
    """同名/同 id/别名已存在 → 返回错误文案，否则空串。"""
    from learner import kp_registry
    for l3 in kp_registry.list_l3_for_l2(subject, l2_name):
        if not isinstance(l3, dict):
            continue
        existing = {
            (l3.get("id") or "").strip(),
            (l3.get("name") or "").strip(),
            *[str(a).strip() for a in (l3.get("aliases") or [])],
        }
        existing.discard("")
        if name in existing:
            return f"已存在同名子考点「{name}」（l3_id={l3.get('id')}），无需添加"
        for a in aliases:
            if a in existing:
                return f"别名「{a}」已存在（l3_id={l3.get('id')}），无需添加"
    return ""


def _load_proposals() -> dict:
    return _load_json(PROPOSALS_PATH, {"proposals": []})


def propose_l3(
    subject: str,
    l2_name: str,
    name: str,
    aliases: list[str] | None = None,
    *,
    staff_id: str = "",
) -> dict:
    """登记一个待确认的 L3 提案；不写入考纲。"""
    subject = (subject or "").strip()
    l2_name = (l2_name or "").strip()
    name = (name or "").strip()
    if subject not in ("math", "comm"):
        return {"ok": False, "error": f"科目不受支持：{subject}"}
    if not l2_name:
        return {"ok": False, "error": "缺少 L2 章节名"}
    if not name:
        return {"ok": False, "error": "缺少子知识点名称"}

    from learner import kp_registry
    kps = (kp_registry.load_syllabus(subject).get("kps") or {})
    if l2_name not in kps:
        resolved = kp_registry.resolve_kp(subject, l2_name)
        if resolved and resolved in kps:
            l2_name = resolved
        else:
            return {
                "ok": False,
                "error": f"考纲中不存在章节「{l2_name}」。只会追加子考点到已有章节，不新建章节。",
            }

    al: list[str] = []
    for a in aliases or []:
        a = (a or "").strip()
        if a and a not in al and a != name:
            al.append(a)

    dup = _dedup_error(subject, l2_name, name, al)
    if dup:
        return {"ok": False, "error": dup}

    all_ids: set[str] = set()
    for meta in kps.values():
        if isinstance(meta, dict):
            for l3 in meta.get("l3") or []:
                if isinstance(l3, dict) and (l3.get("id") or "").strip():
                    all_ids.add(l3["id"].strip())
    props = _load_proposals()
    # 待确认提案已占用的 id 也要避开，防止同章节并发提案撞 id
    all_ids |= {
        str(p.get("l3_id") or "").strip()
        for p in props.get("proposals", [])
        if p.get("status") == "pending" and p.get("l3_id")
    }
    all_ids.discard("")
    l3_id = _gen_l3_id(subject, l2_name, all_ids)

    token = uuid.uuid4().hex[:12]
    props["proposals"] = [
        p for p in props.get("proposals", [])
        if p.get("status") in ("pending", "confirmed")
    ]
    props["proposals"].append({
        "token": token,
        "subject": subject,
        "l2": l2_name,
        "name": name,
        "aliases": al,
        "l3_id": l3_id,
        "staff_id": (staff_id or "").strip(),
        "ts": _now_iso(),
        "status": "pending",
    })
    _save_json(PROPOSALS_PATH, props)
    _audit("propose", token=token, subject=subject, l2=l2_name,
           name=name, l3_id=l3_id)
    return {"ok": True, "token": token, "subject": subject, "l2": l2_name,
            "name": name, "aliases": al, "l3_id": l3_id}


def confirm_l3(token: str, *, staff_id: str = "") -> dict:
    """确认提案并写入考纲（追加 L3）。"""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "缺少确认 token"}
    props = _load_proposals()
    target = None
    for p in props.get("proposals", []):
        if p.get("token") == token:
            target = p
            break
    if not target:
        return {"ok": False, "error": f"找不到提案 {token}（可能已过期或被取消）"}
    if target.get("status") != "pending":
        return {"ok": False, "error": f"提案已处理（status={target.get('status')}），请勿重复确认"}
    sid = (staff_id or "").strip()
    if sid and target.get("staff_id") and sid != target.get("staff_id"):
        return {"ok": False, "error": "该提案不是你提出的，无法确认"}

    subject = target["subject"]
    l2_name = target["l2"]
    path = _syllabus_path(subject)
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": f"考纲文件缺失：{path}"}

    with open(path, encoding="utf-8") as f:
        syl = json.load(f)
    kps = syl.setdefault("kps", {})
    meta = kps.get(l2_name)
    if not isinstance(meta, dict):
        return {"ok": False, "error": f"章节「{l2_name}」已不在考纲中"}
    l3_list = meta.setdefault("l3", [])
    l3_id = target.get("l3_id") or ""
    name = target.get("name") or ""

    # 写入前再查一次重（防止提案期间已被添加）
    for l3 in l3_list:
        if isinstance(l3, dict) and (
            (l3.get("id") or "").strip() == l3_id
            or (l3.get("name") or "").strip() == name
        ):
            target["status"] = "done_dup_at_write"
            _save_json(PROPOSALS_PATH, props)
            return {"ok": False, "error": f"写入时发现已存在「{name}」，已中止"}

    l3_list.append({
        "id": l3_id,
        "name": name,
        "aliases": list(target.get("aliases") or []),
        "rag_queries": [name],
        "source_allow": ["教材", "真题"],
    })
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(syl, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)

    from learner import kp_registry
    kp_registry.reload_registry()

    target["status"] = "confirmed"
    _save_json(PROPOSALS_PATH, props)
    _audit("confirm", token=token, subject=subject, l2=l2_name,
           name=name, l3_id=l3_id)
    return {"ok": True, "subject": subject, "l2": l2_name,
            "name": name, "l3_id": l3_id}


def cancel_l3(token: str, *, staff_id: str = "") -> dict:
    """取消提案（不写入）。"""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "缺少 token"}
    props = _load_proposals()
    target = None
    for p in props.get("proposals", []):
        if p.get("token") == token:
            target = p
            break
    if not target:
        return {"ok": False, "error": f"找不到提案 {token}"}
    if target.get("status") != "pending":
        return {"ok": False, "error": f"提案已处理（status={target.get('status')}）"}
    sid = (staff_id or "").strip()
    if sid and target.get("staff_id") and sid != target.get("staff_id"):
        return {"ok": False, "error": "该提案不是你提出的，无法取消"}
    target["status"] = "cancelled"
    _save_json(PROPOSALS_PATH, props)
    _audit("cancel", token=token, subject=target.get("subject", ""),
           l2=target.get("l2", ""), name=target.get("name", ""))
    return {"ok": True, "token": token, "name": target.get("name", "")}
