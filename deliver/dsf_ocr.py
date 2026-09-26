# -*- coding: utf-8 -*-
"""Handwriting OCR via deepseek-flash vision (decide.router).

SimpleTex mode names from the practice desk / exam page are only prompt hints:
``formula`` / ``latex`` / ``formula_*`` ask for LaTeX; ``document`` / ``page`` /
``general`` / empty ask for a markdown page transcript. Both still return the
transcription as ``text``. The model is asked to emit only the transcript;
``scrub_ocr_text`` strips preamble, fences, and closing chatter anyway.
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
    "You are a handwriting OCR engine for exam answers.\n"
    "Return only the transcription of marks visible in the image.\n"
    "Preserve the writer's language. Do not translate, solve, correct, or complete anything.\n"
    "No preamble, title, analysis, confidence, apology, or closing remark.\n"
    "If a mark is illegible, write [?] there.\n"
    "Put the transcript between these markers and write nothing outside them:\n"
    "<<<OCR>>>\n"
    "<transcript>\n"
    "<<<END>>>"
)

_DOCUMENT_HINT = (
    "This is a page or a mixed crop. Transcribe it as markdown. "
    "Inline math in $...$, display math in $$...$$. "
    "Keep the writer's line breaks and wording. "
    "Do not add headings they did not write."
)

_FORMULA_HINT = (
    "This is a formula crop. Transcribe it as LaTeX only. "
    "No sentences. Bare LaTeX or $$...$$ is fine."
)

_MARK_RE = re.compile(
    r"<<<\s*OCR\s*>>>\s*(.*?)\s*<<<\s*END\s*>>>",
    re.DOTALL | re.IGNORECASE,
)
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_FENCE_LINE_RE = re.compile(r"```[A-Za-z0-9_+-]*")
_LEAD_RE = re.compile(
    r"^(?:"
    r"(?:好的|好|当然|没问题|ok|okay|sure)[，,。.!！\s]*$"
    r"|(?:以下是|下面是|如下是|这里是).{0,48}(?:转写|识别|内容|公式|文字|结果|transcript)"
    r"|(?:这是|这张图|这张图片|图片中|图中|我看到).{0,40}(?:手写|转写|识别|内容|公式|文字|笔记)"
    r"|(?:识别|转写|转录)(?:结果|内容|如下)?\s*[：:]"
    r"|here(?:'s| is)(?: the)? (?:transcription|transcript|ocr|latex|text)\b"
    r"|the (?:handwritten )?(?:transcription|transcript|content)(?: is)?\s*[：:]?"
    r"|(?:transcription|transcript)\s*[：:]"
    r"|公式如下"
    r")",
    re.IGNORECASE,
)
_TAIL_RE = re.compile(
    r"^(?:"
    r"以上(?:是|为)?(?:全部)?(?:识别|转写|转录)?(?:结果|内容)?[。.!！\s]*$"
    r"|以上就是.*"
    r"|如有(?:不清晰|不清楚|看不清|问题|需要|遗漏).*"
    r"|希望(?:这|对你|能帮|有帮助).*"
    r"|(?:请)?告诉我.{0,24}(?:需要|帮助|修正|调整)"
    r"|(?:识别|转写)完成.*"
    r"|我(?:已经)?(?:帮你|为你)?(?:识别|转写).*"
    r"|if you need\b.*"
    r"|let me know\b.*"
    r"|i hope this helps\b.*"
    r")",
    re.IGNORECASE,
)
_META_RE = re.compile(
    r"^(?:\*\*)?(?:分析|解析|点评|总结|说明|备注|注|注释|置信度|置信|confidence)\s*[：:].*",
    re.IGNORECASE,
)
_PAREN_META_RE = re.compile(
    r"^[（(].*(?:模糊|不清|置信|仅供|参考|识别|转写|模型).*[）)]$"
)
_LABEL_ONLY_RE = re.compile(
    r"^(?:转写|识别结果|识别内容|识别|转录|公式|内容|latex|transcription|transcript)"
    r"(?:结果|内容|如下)?\s*[：:]\s*$",
    re.IGNORECASE,
)
_LABEL_PREFIX_RE = re.compile(
    r"^(?:转写|识别结果|识别内容|识别|转录|公式|内容|latex|transcription|transcript)"
    r"(?:结果|内容|如下)?\s*[：:]\s*",
    re.IGNORECASE,
)


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


def _plain(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^>\s*", "", s)
    return re.sub(r"^[*_]+|[*_]+$", "", s).strip()


def _looks_like_math(s: str) -> bool:
    if "$" in s or "\\" in s:
        return True
    return bool(re.search(r"[=^_]", s) and re.search(r"[\dA-Za-z]", s))


def _is_chatter_line(line: str) -> bool:
    plain = _plain(line)
    if not plain:
        return True
    if _FENCE_LINE_RE.fullmatch(plain):
        return True
    if plain in {"---", "***", "——", "———"}:
        return True
    if _META_RE.match(plain) or _PAREN_META_RE.match(plain) or _LABEL_ONLY_RE.match(plain):
        return True
    if _TAIL_RE.match(plain):
        return True
    if _LEAD_RE.match(plain):
        # A formula that merely shares a wrapper word stays in the transcript.
        if _looks_like_math(plain) and not plain.endswith((":", "：")):
            return False
        return True
    return False


def _extract_markers(text: str) -> str | None:
    m = _MARK_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _prefer_fenced_body(text: str) -> str:
    matches = list(_FENCE_RE.finditer(text))
    if not matches:
        return text
    if len(matches) == 1 and text.strip() == matches[0].group(0).strip():
        return matches[0].group(1).strip()
    bodies = [m.group(1).strip() for m in matches if m.group(1).strip()]
    outside = text
    for m in matches:
        outside = outside.replace(m.group(0), "\n", 1)
    outside_lines = [ln for ln in outside.split("\n") if ln.strip()]
    if bodies and (not outside_lines or all(_is_chatter_line(ln) for ln in outside_lines)):
        return "\n\n".join(bodies).strip()
    if len(bodies) == 1 and outside.strip() == bodies[0]:
        return bodies[0]
    return _FENCE_RE.sub(lambda m: "\n" + m.group(1).strip() + "\n", text).strip()


def _strip_edge_chatter(text: str) -> str:
    lines = text.split("\n")
    start, end = 0, len(lines)
    while start < end and _is_chatter_line(lines[start]):
        start += 1
    while end > start and _is_chatter_line(lines[end - 1]):
        end -= 1
    kept = "\n".join(lines[start:end]).strip()
    if kept:
        return kept
    mathish = []
    for ln in lines:
        plain = _plain(ln)
        if plain and _looks_like_math(plain) and not _META_RE.match(plain):
            mathish.append(plain)
    return "\n".join(mathish).strip()


def _strip_label_prefix(text: str) -> str:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        plain = _plain(ln)
        m = _LABEL_PREFIX_RE.match(plain)
        if m and plain[m.end():].strip():
            lines[i] = plain[m.end():].strip()
        break
    return "\n".join(lines).strip()


def _unwrap_quotes(text: str) -> str:
    s = text.strip()
    pairs = (
        ('"""', '"""'),
        ("'''", "'''"),
        ("「", "」"),
        ("『", "』"),
        ("“", "”"),
    )
    for a, b in pairs:
        if len(s) > len(a) + len(b) and s.startswith(a) and s.endswith(b):
            return s[len(a):-len(b)].strip()
    return text


def scrub_ocr_text(raw: str) -> str:
    """Drop wrapper commentary. Keep the handwritten transcript."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u200b", "").strip()
    if not text:
        return ""
    text = _THINK_RE.sub("", text).strip()
    marked = _extract_markers(text)
    if marked is not None:
        text = marked
    text = _prefer_fenced_body(text)
    text = _strip_edge_chatter(text)
    text = _strip_label_prefix(text)
    text = _unwrap_quotes(text)
    text = _strip_edge_chatter(text)
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())
    return text.strip()


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
