# -*- coding: utf-8 -*-
"""私聊入站图片暂存：供 Cow 工具按需 OCR/批改，不机械全量送系统。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from config import DATA_DIR

_LOCK = threading.RLock()
_ROOT = os.path.join(DATA_DIR, "inbound_images")
_TTL_SEC = 6 * 3600  # 6h


def _learner_dir(learner_id: str) -> str:
    safe = "".join(c for c in (learner_id or "unknown") if c.isalnum() or c in "-_")[:64]
    return os.path.join(_ROOT, safe or "unknown")


def stash_image(
    learner_id: str,
    image_bytes: bytes,
    *,
    filename: str = "photo.jpg",
    caption: str = "",
) -> str:
    """写入暂存，返回 image_id。"""
    if not image_bytes:
        raise ValueError("empty image")
    lid = (learner_id or "").strip() or "unknown"
    image_id = uuid.uuid4().hex[:16]
    d = _learner_dir(lid)
    os.makedirs(d, exist_ok=True)
    bin_path = os.path.join(d, f"{image_id}.bin")
    meta_path = os.path.join(d, f"{image_id}.json")
    latest_path = os.path.join(d, "latest.json")
    meta = {
        "image_id": image_id,
        "learner_id": lid,
        "filename": filename,
        "caption": (caption or "").strip(),
        "bytes": len(image_bytes),
        "created_at": time.time(),
    }
    with _LOCK:
        with open(bin_path, "wb") as f:
            f.write(image_bytes)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump({"image_id": image_id}, f)
        _cleanup_old(d)
    return image_id


def _cleanup_old(d: str) -> None:
    now = time.time()
    try:
        for name in os.listdir(d):
            if not name.endswith(".json") or name == "latest.json":
                continue
            path = os.path.join(d, name)
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.load(f)
                if now - float(meta.get("created_at") or 0) > _TTL_SEC:
                    iid = meta.get("image_id") or name[:-5]
                    for p in (
                        os.path.join(d, f"{iid}.bin"),
                        os.path.join(d, f"{iid}.json"),
                    ):
                        if os.path.isfile(p):
                            os.remove(p)
            except Exception:
                continue
    except OSError:
        pass


def resolve_image(learner_id: str, image_id: str = "") -> tuple[str, bytes, dict[str, Any]]:
    """返回 (image_id, bytes, meta)。image_id 空则取该学员最新一张。"""
    lid = (learner_id or "").strip() or "unknown"
    d = _learner_dir(lid)
    iid = (image_id or "").strip()
    with _LOCK:
        if not iid:
            latest_path = os.path.join(d, "latest.json")
            if not os.path.isfile(latest_path):
                raise FileNotFoundError("no_pending_image")
            with open(latest_path, encoding="utf-8") as f:
                iid = str((json.load(f) or {}).get("image_id") or "")
        if not iid:
            raise FileNotFoundError("no_pending_image")
        meta_path = os.path.join(d, f"{iid}.json")
        bin_path = os.path.join(d, f"{iid}.bin")
        if not os.path.isfile(bin_path):
            raise FileNotFoundError(f"image_not_found:{iid}")
        with open(bin_path, "rb") as f:
            data = f.read()
        meta: dict[str, Any] = {}
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f) or {}
        return iid, data, meta


def extract_picture_download_codes(raw: dict) -> list[str]:
    """从 picture / richText 消息提取 downloadCode 列表。"""
    if not isinstance(raw, dict):
        return []
    msgtype = str(raw.get("msgtype") or "").strip()
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    codes: list[str] = []

    def _add(dc: Any) -> None:
        s = str(dc or "").strip()
        if s and s not in codes:
            codes.append(s)

    mt = msgtype.lower()
    if mt == "picture":
        _add(content.get("downloadCode") or raw.get("downloadCode"))
    elif mt == "richtext":
        items = content.get("richText") or content.get("richtext") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                typ = str(it.get("type") or "").lower()
                if typ == "picture" or it.get("downloadCode"):
                    _add(it.get("downloadCode"))
    else:
        # 兜底：content 里直接带 downloadCode
        _add(content.get("downloadCode"))
    return codes


def extract_rich_text_caption(raw: dict) -> str:
    if not isinstance(raw, dict):
        return ""
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    items = content.get("richText") or content.get("richtext") or []
    parts: list[str] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("text"):
                parts.append(str(it["text"]))
    return "\n".join(p.strip() for p in parts if str(p).strip()).strip()
