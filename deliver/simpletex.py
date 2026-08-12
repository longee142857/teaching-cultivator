# -*- coding: utf-8 -*-
"""SimpleTex 手写/公式 OCR 客户端（北京域名直连，不走代理翻墙）。"""
from __future__ import annotations

import datetime
import hashlib
import logging
import secrets
from typing import Any

import requests

from config import SSL_VERIFY

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://server.simpletex.cn"


def _cfg():
    from config import (
        SIMPLETEX_APP_ID,
        SIMPLETEX_APP_SECRET,
        SIMPLETEX_API_BASE,
        SIMPLETEX_OCR_MODE,
        SIMPLETEX_UAT,
    )

    return {
        "app_id": (SIMPLETEX_APP_ID or "").strip(),
        "app_secret": (SIMPLETEX_APP_SECRET or "").strip(),
        "uat": (SIMPLETEX_UAT or "").strip(),
        "base": (SIMPLETEX_API_BASE or DEFAULT_BASE).rstrip("/"),
        "mode": (SIMPLETEX_OCR_MODE or "general").strip().lower(),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["uat"] or (c["app_id"] and c["app_secret"]))


def _auth_headers(form_data: dict[str, Any]) -> dict[str, str]:
    c = _cfg()
    if c["uat"]:
        return {"token": c["uat"]}
    if not (c["app_id"] and c["app_secret"]):
        raise RuntimeError("未配置 SIMPLETEX_UAT 或 SIMPLETEX_APP_ID/SECRET")
    header = {
        "timestamp": str(int(datetime.datetime.now().timestamp())),
        "random-str": secrets.token_hex(8),
        "app-id": c["app_id"],
    }
    keys = sorted(list(form_data.keys()) + list(header.keys()))
    parts = []
    for key in keys:
        if key in header:
            parts.append(f"{key}={header[key]}")
        else:
            parts.append(f"{key}={form_data[key]}")
    pre = "&".join(parts) + f"&secret={c['app_secret']}"
    header["sign"] = hashlib.md5(pre.encode("utf-8")).hexdigest()
    return header


def _endpoint(mode: str) -> tuple[str, dict[str, Any]]:
    """返回 (path, 非文件表单字段)。"""
    if mode in ("formula", "formula_std", "latex"):
        return "/api/latex_ocr", {}
    if mode in ("formula_turbo", "turbo", "lightweight"):
        return "/api/latex_ocr_turbo", {}
    # general：整页/演算混排（免费量较少但更适合答卷）
    return "/api/simpletex_ocr", {
        "rec_mode": "auto",
        "enable_img_rot": "true",
    }


def _extract_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("status") is False:
        return ""
    # simpletex_ocr(general) 常用 res.info；latex_* 用 res.latex
    keys = ("latex", "markdown", "text", "content", "md", "info")

    def _pick(d: dict) -> str:
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and v.strip() and v.strip() != "[EMPTY]":
                return v.strip()
        return ""

    res = payload.get("res")
    if isinstance(res, dict):
        hit = _pick(res)
        if hit:
            return hit
        # nested（偶发多块）
        for sub in res.values():
            if isinstance(sub, dict):
                hit = _pick(sub)
                if hit:
                    return hit
            elif isinstance(sub, list):
                parts = []
                for item in sub:
                    if isinstance(item, dict):
                        t = _pick(item)
                        if t:
                            parts.append(t)
                    elif isinstance(item, str) and item.strip():
                        parts.append(item.strip())
                if parts:
                    return "\n".join(parts)
    hit = _pick(payload) if isinstance(payload, dict) else ""
    return hit


def ocr_image(
    image_bytes: bytes,
    *,
    filename: str = "answer.jpg",
    mode: str | None = None,
) -> dict[str, Any]:
    """识别图片。返回 {ok, text, conf, raw, error, mode}。"""
    if not image_bytes:
        return {"ok": False, "text": "", "conf": None, "raw": None, "error": "empty_image", "mode": mode}
    if not is_configured():
        return {
            "ok": False,
            "text": "",
            "conf": None,
            "raw": None,
            "error": "simpletex_not_configured",
            "mode": mode,
        }
    c = _cfg()
    use_mode = (mode or c["mode"] or "general").strip().lower()
    path, form = _endpoint(use_mode)
    url = c["base"] + path
    try:
        headers = _auth_headers(form)
        files = {"file": (filename, image_bytes, "application/octet-stream")}
        resp = requests.post(
            url,
            headers=headers,
            data=form,
            files=files,
            timeout=90,
            verify=SSL_VERIFY,
            proxies={"http": None, "https": None},
        )
        raw: Any
        try:
            raw = resp.json()
        except Exception:
            raw = {"_text": resp.text[:500], "status_code": resp.status_code}
        if resp.status_code >= 400:
            return {
                "ok": False,
                "text": "",
                "conf": None,
                "raw": raw,
                "error": f"http_{resp.status_code}",
                "mode": use_mode,
            }
        text = _extract_text(raw if isinstance(raw, dict) else {})
        conf = None
        if isinstance(raw, dict):
            res = raw.get("res") if isinstance(raw.get("res"), dict) else {}
            if isinstance(res, dict) and "conf" in res:
                try:
                    conf = float(res["conf"])
                except (TypeError, ValueError):
                    conf = None
        if not text:
            return {
                "ok": False,
                "text": "",
                "conf": conf,
                "raw": raw,
                "error": "empty_ocr",
                "mode": use_mode,
            }
        return {"ok": True, "text": text, "conf": conf, "raw": raw, "error": "", "mode": use_mode}
    except Exception as e:
        logger.warning("simpletex ocr failed: %s", e)
        return {
            "ok": False,
            "text": "",
            "conf": None,
            "raw": None,
            "error": str(e),
            "mode": use_mode,
        }
