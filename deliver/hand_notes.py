"""手写笔记图片：按学员存在 data/hand_notes/<learner>/。"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "hand_notes")
MAX_BYTES = 4_000_000


def _safe(learner: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", learner or "")[:32]


def _folder(learner: str) -> str:
    return os.path.join(DIR, _safe(learner))


def _index_path(learner: str) -> str:
    return os.path.join(_folder(learner), "index.json")


def list_notes(learner: str) -> dict:
    lid = _safe(learner)
    if not lid:
        return {"ok": False, "error": "learner_required"}
    path = _index_path(lid)
    if not os.path.isfile(path):
        return {"ok": True, "notes": []}
    try:
        notes = json.loads(open(path, encoding="utf-8").read() or "[]")
    except (OSError, json.JSONDecodeError):
        notes = []
    if not isinstance(notes, list):
        notes = []
    public = [
        {k: n[k] for k in ("id", "name", "mime", "created_at") if k in n}
        for n in notes
        if isinstance(n, dict) and n.get("id")
    ]
    return {"ok": True, "notes": public}


def save_note(learner: str, image: str, name: str = "") -> dict:
    lid = _safe(learner)
    if not lid:
        return {"ok": False, "error": "learner_required"}
    raw = image or ""
    mime = "image/jpeg"
    if raw.startswith("data:"):
        head, _, b64 = raw.partition(",")
        matched = re.search(r"data:([^;]+)", head)
        if matched:
            mime = matched.group(1)[:80]
        raw = b64
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception:
        return {"ok": False, "error": "bad_image"}
    if not blob:
        return {"ok": False, "error": "empty_image"}
    if len(blob) > MAX_BYTES:
        return {"ok": False, "error": "image_too_large"}
    if "png" in mime:
        ext = "png"
    elif "webp" in mime:
        ext = "webp"
    else:
        ext = "jpg"
        mime = mime if mime.startswith("image/") else "image/jpeg"
    nid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = _folder(lid)
    os.makedirs(folder, exist_ok=True)
    fname = nid + "." + ext
    with open(os.path.join(folder, fname), "wb") as f:
        f.write(blob)
    entry = {
        "id": nid,
        "name": (name or "手写笔记")[:80],
        "mime": mime,
        "file": fname,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = _index_path(lid)
    notes: list = []
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
            if isinstance(loaded, list):
                notes = loaded
        except (OSError, json.JSONDecodeError):
            notes = []
    notes.insert(0, entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes[:200], f, ensure_ascii=False, indent=2)
    return {"ok": True, "note": {k: entry[k] for k in ("id", "name", "mime", "created_at")}}


def read_note(learner: str, note_id: str, *, with_image: bool = False) -> dict:
    lid = _safe(learner)
    nid = re.sub(r"[^A-Za-z0-9_-]", "", note_id or "")
    if not lid or not nid:
        return {"ok": False, "error": "not_found"}
    path = _index_path(lid)
    notes: list = []
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
            if isinstance(loaded, list):
                notes = loaded
        except (OSError, json.JSONDecodeError):
            notes = []
    hit = next((n for n in notes if isinstance(n, dict) and n.get("id") == nid), None)
    if not hit:
        return {"ok": False, "error": "not_found"}
    file_path = os.path.join(_folder(lid), str(hit.get("file") or ""))
    if not os.path.isfile(file_path):
        return {"ok": False, "error": "not_found"}
    out = {
        "ok": True,
        "note": {k: hit[k] for k in ("id", "name", "mime", "created_at") if k in hit},
    }
    if with_image:
        blob = open(file_path, "rb").read()
        mime = str(hit.get("mime") or "image/jpeg")
        out["data_url"] = "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode("ascii"))
    return out
