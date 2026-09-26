# -*- coding: utf-8 -*-
"""Handwriting OCR via deepseek-flash vision (decide.router).

SimpleTex mode names from the practice desk / exam page are only prompt hints:
``formula`` / ``latex`` / ``formula_*`` ask for LaTeX; ``document`` / ``page`` /
``general`` / empty ask for a markdown page transcript. Both still return the
transcription as ``text``.

The prompt asks the model to copy exponents, radical indices, and digits as
written. ``scrub_ocr_text`` is a light safety net for an occasional fence or
one-line wrapper; it does not rewrite math.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 3_500_000
OCR_TIMEOUT_S = 90

_FORMULA_MODES = frozenset({
    "formula",
    "latex",
    "formula_std",
    "formula_turbo",
    "turbo",
    "lightweight",
})

_SYSTEM = (
    "You transcribe handwritten exam answers. Output the transcription only.\n"
    "Do not translate, solve, correct, simplify, or complete the handwriting.\n"
    "Copy symbols exactly.\n"
    "Preserve superscripts in full: 2^{2N} is not 2^N. Copy every character in an exponent.\n"
    "Double-check every digit. Copy it as written; do not swap a similar digit.\n"
    "Copy radical indices exactly: 1/\\sqrt{6} is not 1/\\sqrt{5}.\n"
    "If a mark is illegible, write [?]."
)

_DOCUMENT_HINT = (
    "Transcribe the page as markdown. "
    "Inline math in $...$, display math in $$...$$. "
    "Keep the writer's line breaks and wording."
)

_FORMULA_HINT = (
    "Transcribe this crop as LaTeX only. "
    "No surrounding sentences. Bare LaTeX or $$...$$ is fine."
)

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_MARK_RE = re.compile(
    r"<<<\s*OCR\s*>>>\s*(.*?)\s*<<<\s*END\s*>>>",
    re.DOTALL | re.IGNORECASE,
)
_WHOLE_FENCE_RE = re.compile(r"^```[^\n`]*\n(.*)\n```$", re.DOTALL)
# Whole-line wrappers only. A line with a digit or math mark is left alone.
_EDGE_RE = re.compile(
    r"^(?:"
    r"```[A-Za-z0-9_+-]*"
    r"|(?:好的|当然|ok|okay|sure)[，,。.!！\s]*"
    r"|(?:以下是|下面是|这是).{0,32}(?:识别结果|转写结果|转写|识别)[：:。.!！\s]*"
    r"|以上是识别结果[。.!！\s]*"
    r"|(?:置信度|置信|confidence)\s*[：:]\s*\S{0,8}"
    r")$",
    re.IGNORECASE,
)
_MATHISH_RE = re.compile(r"[$\\^_=√\d]")


def is_configured() -> bool:
    """True when a DeepSeek key is available. Empty env wins over a stale import."""
    if "DEEPSEEK_API_KEY" in os.environ:
        return bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())
    try:
        from config import DEEPSEEK_API_KEY

        return bool((DEEPSEEK_API_KEY or "").strip())
    except Exception:
        return False


def normalize_mode(mode: str | None) -> str:
    """Map caller / SimpleTex mode names onto ``document`` or ``formula``."""
    m = (mode or "").strip().lower()
    if m in _FORMULA_MODES:
        return "formula"
    return "document"


def _edge_wrapper(line: str) -> bool:
    s = line.strip().strip("*_")
    if not s:
        return True
    if _MATHISH_RE.search(s):
        return False
    return bool(_EDGE_RE.match(s))


def _strip_edge_wrappers(text: str) -> str:
    lines = text.split("\n")
    while lines and _edge_wrapper(lines[0]):
        lines.pop(0)
    while lines and _edge_wrapper(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _unwrap_whole_fence(text: str) -> str:
    m = _WHOLE_FENCE_RE.match(text.strip())
    if not m:
        return text
    return m.group(1).strip()


def scrub_ocr_text(raw: str) -> str:
    """Drop an occasional fence or one-line wrapper. Do not rewrite math."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u200b", "").strip()
    if not text:
        return ""
    text = _THINK_RE.sub("", text).strip()
    marked = _MARK_RE.search(text)
    if marked and marked.group(1).strip():
        text = marked.group(1).strip()
    for _ in range(3):
        stripped = _strip_edge_wrappers(text)
        unwrapped = _unwrap_whole_fence(stripped)
        if unwrapped == text:
            break
        text = unwrapped
    lines = [ln.rstrip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def _mime(filename: str, data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    ext = ""
    if "." in (filename or ""):
        ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")


def _message_text(data: dict) -> str:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return ""


def _fail(error: str, mode: str) -> dict[str, Any]:
    return {
        "ok": False,
        "text": "",
        "conf": None,
        "raw": None,
        "error": error,
        "mode": mode,
    }


def ocr_image(
    image_bytes: bytes,
    *,
    filename: str = "answer.jpg",
    mode: str | None = None,
) -> dict[str, Any]:
    """Recognize handwriting. Returns ``{ok, text, conf, raw, error, mode}``.

    ``conf`` is always null: deepseek-flash does not return a calibrated score.
    ``text`` is the scrubbed transcript only.
    """
    use_mode = normalize_mode(mode)
    if not image_bytes:
        return _fail("empty_image", use_mode)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return _fail("image_too_large", use_mode)
    if not is_configured():
        return _fail("deepseek_not_configured", use_mode)

    from decide.router import call_deepseek_chat, select_model

    cfg = select_model("ocr")
    hint = _FORMULA_HINT if use_mode == "formula" else _DOCUMENT_HINT
    mime = _mime(filename or "answer.jpg", image_bytes)
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": hint},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    logger.info(
        "dsf ocr model=%s mode=%s bytes=%s",
        cfg.model,
        use_mode,
        len(image_bytes),
    )
    try:
        # Thinking stays off: reasoning text is not part of the transcript.
        data = call_deepseek_chat(
            messages,
            model=cfg.model,
            thinking=False,
            timeout=OCR_TIMEOUT_S,
        )
    except Exception as e:
        logger.warning("dsf ocr failed: %s: %s", type(e).__name__, e)
        status = getattr(getattr(e, "response", None), "status_code", None)
        name = type(e).__name__
        if status:
            err = f"http_{int(status)}"
        elif name in ("Timeout", "ConnectTimeout", "ReadTimeout"):
            err = "timeout"
        elif "DEEPSEEK_API_KEY" in str(e):
            err = "deepseek_not_configured"
        else:
            err = "ocr_failed"
        return _fail(err, use_mode)

    raw_text = _message_text(data if isinstance(data, dict) else {})
    text = scrub_ocr_text(raw_text)
    if not text:
        return _fail("empty_ocr", use_mode)
    return {
        "ok": True,
        "text": text,
        "conf": None,
        "raw": None,
        "error": "",
        "mode": use_mode,
    }
