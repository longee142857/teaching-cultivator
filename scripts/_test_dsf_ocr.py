# -*- coding: utf-8 -*-
"""deepseek-flash handwriting OCR: scrubber + mocked vision call (no network)."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fails = 0
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CLEAN = r"\int_0^1 x^2\,dx = \frac{1}{3}"


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


def test_scrub() -> None:
    from deliver.dsf_ocr import scrub_ocr_text

    check(scrub_ocr_text(CLEAN) == CLEAN, "clean latex passes through")
    symbols = "2^{2N}\nN=6 dB 37.88\n1/\\sqrt{6}"
    check(scrub_ocr_text(symbols) == symbols, "exponents, digits, radicals untouched")
    check(
        scrub_ocr_text(f"<<<OCR>>>\n{CLEAN}\n<<<END>>>") == CLEAN,
        "marker wrapper stripped when present",
    )
    noisy = (
        "以下是识别结果：\n\n"
        "```latex\n"
        "2^{2N}\n"
        "```\n\n"
        "以上是识别结果。\n"
    )
    check(scrub_ocr_text(noisy) == "2^{2N}", "one-line wrapper and fence stripped")
    page = (
        "以下是转写结果：\n\n"
        "这是极限存在的充要条件。\n\n"
        "$$L$$\n\n"
        "以上证明了该极限为 1。\n"
    )
    kept = scrub_ocr_text(page)
    check("这是极限存在的充要条件。" in kept, "real 这是 sentence kept")
    check("以上证明了该极限为 1。" in kept, "proof closing kept")
    check("以下是转写结果" not in kept, "preamble line dropped")
    think = f"<think>draft the latex</think>\n{CLEAN}"
    check(scrub_ocr_text(think) == CLEAN, "think block dropped")
    check(scrub_ocr_text("公式：$x^{2}$") == "公式：$x^{2}$", "math line is not rewritten")
    check(scrub_ocr_text("以下是识别结果：\n以上是识别结果。") == "", "wrapper-only is empty")
    check(scrub_ocr_text("") == "", "empty scrub")


def test_ocr_image_mock() -> None:
    from config import MODEL_FLASH
    from deliver.dsf_ocr import OCR_TIMEOUT_S, ocr_image

    png = b"\x89PNG\r\n\x1a\nnot-really"
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=_chat(f"<<<OCR>>>\n{CLEAN}\n<<<END>>>")) as mock:
        out = ocr_image(png, filename="a.png", mode="formula")
        check(out["ok"] is True and out["text"] == CLEAN, "mocked clean reply")
        check(out["conf"] is None and out["error"] == "" and out["mode"] == "formula", "shape")
        check(out["raw"] is None, "raw chatter is not returned")
        messages = mock.call_args.args[0]
        kwargs = mock.call_args.kwargs
        check(kwargs.get("model") == MODEL_FLASH, "model is MODEL_FLASH")
        check(kwargs.get("thinking") is False, "thinking off")
        check(kwargs.get("timeout") == OCR_TIMEOUT_S, "ocr timeout")
        user = messages[1]["content"]
        check(isinstance(user, list) and user[0]["type"] == "text", "vision text part")
        check("LaTeX" in user[0]["text"], "formula mode prompt")
        system = messages[0]["content"]
        check("2^{2N}" in system and "2^N" in system, "prompt keeps full superscripts")
        check("sqrt" in system, "prompt checks radical indices")
        check("digit" in system.lower(), "prompt checks digits")
        check("<<<OCR>>>" not in system, "prompt does not require marker wrappers")
        check(user[1]["image_url"]["url"].startswith("data:image/png;base64,"), "png data url")

    noisy = (
        "以下是识别结果：\n\n```markdown\n"
        "已知 $f(x)=x^2$。\n\n$$f'(x)=2x$$\n```\n\n以上是识别结果。\n"
    )
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=_chat(noisy)) as mock:
        out = ocr_image(png, filename="page.jpg", mode="document")
        check(out["ok"] is True, "noisy reply ok")
        check("已知 $f(x)=x^2$。" in out["text"], "page transcript kept")
        check("$$f'(x)=2x$$" in out["text"], "display math kept")
        check("以下是识别结果" not in out["text"] and "以上是识别结果" not in out["text"], "wrappers gone")
        check("markdown" in mock.call_args.args[0][1]["content"][0]["text"], "document mode prompt")

    listed = {"choices": [{"message": {"content": [{"type": "text", "text": CLEAN}]}}]}
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=listed):
        out = ocr_image(png, filename="a.png", mode="")
        check(out["text"] == CLEAN and out["mode"] == "document", "list content + empty mode")

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=_chat("   ")) as mock:
        out = ocr_image(png, filename="a.png")
        check(out["ok"] is False and out["error"] == "empty_ocr" and out["text"] == "", "empty model text")
        check(mock.called, "empty text still called the model")

    class _Resp:
        status_code = 401

    class _HTTP(Exception):
        def __init__(self) -> None:
            self.response = _Resp()

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", side_effect=_HTTP()):
        out = ocr_image(png, filename="a.png")
        check(out["ok"] is False and out["error"] == "http_401", "http error")

    class ReadTimeout(Exception):
        pass

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", side_effect=ReadTimeout()):
        out = ocr_image(png, filename="a.png")
        check(out["error"] == "timeout", "timeout")

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False), \
         patch("decide.router.call_deepseek_chat") as mock:
        out = ocr_image(png, filename="a.png")
        check(out["error"] == "deepseek_not_configured", "missing key")
        check(mock.called is False, "missing key does not call")

    check(ocr_image(b"", filename="a.png")["error"] == "empty_image", "empty bytes")
    with patch("decide.router.call_deepseek_chat") as mock:
        big = ocr_image(b"x" * 3_500_001, filename="a.png")
        check(big["error"] == "image_too_large", "too large")
        check(mock.called is False, "too large does not call")

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=_chat(CLEAN)) as mock:
        out = ocr_image(png, filename="a.png", mode="formula_turbo")
        check(out["mode"] == "formula", "formula_turbo maps to formula prompt")
        check("LaTeX" in mock.call_args.args[0][1]["content"][0]["text"], "turbo still latex hint")


def test_practice_ocr_and_manifest() -> None:
    from config import MODEL_FLASH
    from modules.bridge.practice_service import agent_manifest, practice_ocr

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False), \
         patch("decide.router.call_deepseek_chat", return_value=_chat(CLEAN)) as mock, \
         patch("deliver.simpletex.ocr_image", side_effect=AssertionError("simpletex called")):
        out = practice_ocr(TINY_PNG_B64, filename="hw.png", mode="formula")
        check(out["ok"] is True and out["text"] == CLEAN, "practice_ocr uses dsf")
        check(mock.called, "practice_ocr called deepseek")
        man = agent_manifest()["practice"]["ocr"]
        check(man["backend"] == "decide.router", "manifest backend")
        check(man["status"] == MODEL_FLASH, "manifest status is the flash id")
        check(man["model"] == MODEL_FLASH, "manifest model")
        check("simpletex" not in man["backend"] and "simpletex" not in man["status"], "manifest not simpletex")

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
        man = agent_manifest()["practice"]["ocr"]
        check(man["status"] == "stub_501", "unwired manifest is stub_501")
        check(man["backend"] == "decide.router", "unwired backend still decide.router")


def test_ui_copy() -> None:
    shell = open(os.path.join(ROOT, "web/static/teaching-shell.html"), encoding="utf-8").read()
    exam = open(os.path.join(ROOT, "web/static/exam.html"), encoding="utf-8").read()
    check("deepseek_not_configured" in shell and "deepseek_not_configured" in exam, "ui maps missing key")
    check("标准公式模型" not in exam, "exam copy no longer names the SimpleTex formula model")


def main() -> int:
    print("== dsf ocr ==")
    test_scrub()
    test_ocr_image_mock()
    test_practice_ocr_and_manifest()
    test_ui_copy()
    print("=" * 40)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL DSF OCR TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
