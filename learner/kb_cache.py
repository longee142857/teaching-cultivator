"""云端考点小库 + 知识回填请求队列。

流程：
  1. 出题前 lookup(subject, kp) → 命中则注入 prompt
  2. miss → enqueue，对话/推送不阻塞
  3. 本机开机后 sync_kb_cache 查本地 Chroma → upsert + ack
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR

STORE_PATH = os.path.join(DATA_DIR, "kb_cache", "store.json")
QUEUE_PATH = os.path.join(DATA_DIR, "kb_request_queue.jsonl")
MAX_ENTRIES = 400  # L2×60 + L3 预热（011-rag）；原 120 不够
MAX_SNIPPETS = 4
SNIPPET_TEXT_LEN = 400
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(subject: str, kp: str) -> str:
    return f"{subject}::{kp}"


def _ensure_dirs() -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_store() -> dict:
    _ensure_dirs()
    try:
        if os.path.isfile(STORE_PATH):
            with open(STORE_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("entries"), dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"entries": {}, "updated_at": _now()}


def _save_store(store: dict) -> None:
    _ensure_dirs()
    store["updated_at"] = _now()
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STORE_PATH)


def _evict_if_needed(store: dict) -> None:
    entries: dict = store.get("entries") or {}
    if len(entries) <= MAX_ENTRIES:
        return
    # 先按 hits 升序，再按 updated_at 升序
    ranked = sorted(
        entries.items(),
        key=lambda kv: (
            int((kv[1] or {}).get("hits") or 0),
            str((kv[1] or {}).get("updated_at") or ""),
        ),
    )
    drop_n = len(entries) - MAX_ENTRIES
    for k, _ in ranked[:drop_n]:
        entries.pop(k, None)


def peek(subject: str, kp: str) -> dict | None:
    """只读查看，不增加 hits。"""
    if not subject or not kp or subject == "review":
        return None
    with _lock:
        store = _load_store()
        entry = (store.get("entries") or {}).get(_key(subject, kp))
        return dict(entry) if entry else None


def lookup(subject: str, kp: str) -> dict | None:
    """命中返回 entry dict，否则 None。命中时 hits+1（用于出题注入）。"""
    if not subject or not kp or subject == "review":
        return None
    with _lock:
        store = _load_store()
        entry = (store.get("entries") or {}).get(_key(subject, kp))
        if not entry:
            return None
        entry["hits"] = int(entry.get("hits") or 0) + 1
        entry["last_hit_at"] = _now()
        store["entries"][_key(subject, kp)] = entry
        _save_store(store)
        return dict(entry)


def entry_to_rag_items(entry: dict | None) -> list[dict]:
    if not entry:
        return []
    items = []
    for s in (entry.get("snippets") or [])[:MAX_SNIPPETS]:
        if not isinstance(s, dict):
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        items.append({
            "source": s.get("source") or "kb_cache",
            "page": s.get("page") or "",
            "distance": s.get("distance", 0.0),
            "text": text[:SNIPPET_TEXT_LEN],
        })
    return items


def _pending_keys() -> set[str]:
    keys: set[str] = set()
    if not os.path.isfile(QUEUE_PATH):
        return keys
    try:
        with open(QUEUE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("status") == "pending":
                    keys.add(_key(row.get("subject", ""), row.get("kp", "")))
    except OSError:
        pass
    return keys


def enqueue(
    subject: str,
    kp: str,
    *,
    query: str = "",
    reason: str = "miss",
) -> dict:
    """登记回填请求；同 subject+kp 已有 pending 则去重。"""
    if not subject or not kp or subject == "review":
        return {"ok": False, "error": "invalid subject/kp"}
    q = (query or kp).strip()
    with _lock:
        if _key(subject, kp) in _pending_keys():
            return {"ok": True, "deduped": True, "subject": subject, "kp": kp}
        # 已有缓存也不重复排队（除非强制）
        store = _load_store()
        if _key(subject, kp) in (store.get("entries") or {}):
            return {"ok": True, "cached": True, "subject": subject, "kp": kp}

        req_id = uuid.uuid4().hex[:12]
        row = {
            "id": req_id,
            "ts": _now(),
            "subject": subject,
            "kp": kp,
            "query": q,
            "status": "pending",
            "reason": reason,
            "source_hints": _default_source_hints(subject),
        }
        _ensure_dirs()
        with open(QUEUE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "id": req_id, "subject": subject, "kp": kp}


def _default_source_hints(subject: str) -> list[str]:
    if subject == "math":
        return ["卓里奇", "线性代数", "高等数学", "概率", "真题"]
    if subject == "comm":
        return ["周炯槃", "通信原理", "真题"]
    return []


def fetch_rag_for_prompt(subject: str, kp: str) -> tuple[list[dict], str]:
    """出题用：返回 (rag_items, status)。

    status: hit | queued | skip
    """
    if subject not in ("math", "comm") or not kp:
        return [], "skip"
    entry = lookup(subject, kp)
    items = entry_to_rag_items(entry)
    if items:
        return items, "hit"
    enq = enqueue(subject, kp, query=kp, reason="prompt_miss")
    if enq.get("ok"):
        return [], "queued"
    return [], "skip"


def upsert(
    subject: str,
    kp: str,
    snippets: list[dict],
    *,
    query: str = "",
    request_id: str = "",
) -> dict:
    """写入/更新小库条目。"""
    if not subject or not kp:
        return {"ok": False, "error": "invalid"}
    clean: list[dict] = []
    for s in snippets or []:
        if not isinstance(s, dict):
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        clean.append({
            "source": s.get("source") or "?",
            "page": s.get("page") or "",
            "distance": s.get("distance", 0.0),
            "text": text[:SNIPPET_TEXT_LEN],
        })
        if len(clean) >= MAX_SNIPPETS:
            break
    if not clean:
        return {"ok": False, "error": "empty snippets"}

    with _lock:
        store = _load_store()
        entries = store.setdefault("entries", {})
        key = _key(subject, kp)
        old = entries.get(key) or {}
        entries[key] = {
            "subject": subject,
            "kp": kp,
            "query": query or old.get("query") or kp,
            "snippets": clean,
            "updated_at": _now(),
            "hits": int(old.get("hits") or 0),
            "from_request": request_id or old.get("from_request") or "",
        }
        _evict_if_needed(store)
        _save_store(store)
    return {"ok": True, "key": key, "n": len(clean)}


def list_pending(limit: int = 50) -> list[dict]:
    rows: list[dict] = []
    if not os.path.isfile(QUEUE_PATH):
        return rows
    try:
        with open(QUEUE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("status") == "pending":
                    rows.append(row)
                    if len(rows) >= limit:
                        break
    except OSError:
        pass
    return rows


def ack(ids: list[str], *, status: str = "done", note: str = "") -> int:
    """将队列中指定 id 标为 done/failed（重写整文件）。"""
    if not ids:
        return 0
    id_set = set(ids)
    with _lock:
        if not os.path.isfile(QUEUE_PATH):
            return 0
        kept: list[dict] = []
        n = 0
        try:
            with open(QUEUE_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("id") in id_set and row.get("status") == "pending":
                        row["status"] = status
                        row["acked_at"] = _now()
                        if note:
                            row["note"] = note
                        n += 1
                    kept.append(row)
            tmp = QUEUE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for row in kept:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp, QUEUE_PATH)
        except OSError:
            return 0
    return n


def apply_fulfillments(items: list[dict]) -> dict[str, Any]:
    """批量应用本机回填结果。"""
    ok = 0
    fail = 0
    acked: list[str] = []
    for it in items:
        subject = it.get("subject") or ""
        kp = it.get("kp") or ""
        snippets = it.get("snippets") or []
        req_id = it.get("id") or ""
        r = upsert(subject, kp, snippets, query=it.get("query") or kp, request_id=req_id)
        if r.get("ok"):
            ok += 1
            if req_id:
                acked.append(req_id)
        else:
            fail += 1
            if req_id:
                ack([req_id], status="failed", note=r.get("error", ""))
    if acked:
        ack(acked, status="done")
    return {"ok": ok, "fail": fail, "acked": len(acked)}


def stats() -> dict:
    store = _load_store()
    pending = list_pending(limit=1000)
    return {
        "entries": len(store.get("entries") or {}),
        "pending": len(pending),
        "store_path": STORE_PATH,
        "queue_path": QUEUE_PATH,
    }
