# -*- coding: utf-8 -*-
"""SimpleTex OCR + 私聊图暂存 + Cow 工具（无真网）。"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def test_sign_and_extract() -> None:
    from deliver import simpletex as st

    form = {"rec_mode": "auto"}
    with patch.dict(
        os.environ,
        {
            "SIMPLETEX_UAT": "",
            "SIMPLETEX_APP_ID": "19X4f10YM1Va894nvFl89ikY",
            "SIMPLETEX_APP_SECRET": "fu4Wfmna4153DFN12ctBsPqgVI3vvGGK",
        },
        clear=False,
    ):
        with patch.object(st, "_cfg", return_value={
            "app_id": "19X4f10YM1Va894nvFl89ikY",
            "app_secret": "fu4Wfmna4153DFN12ctBsPqgVI3vvGGK",
            "uat": "",
            "base": "https://server.simpletex.cn",
            "mode": "general",
        }):
            with patch("deliver.simpletex.datetime") as mock_dt:
                mock_dt.datetime.now.return_value.timestamp.return_value = 1675550577
                with patch("deliver.simpletex.secrets.token_hex", return_value="mSkYSY28N4WkvidB"):
                    h = st._auth_headers(form)
                    check("app-id" in h and "sign" in h and "timestamp" in h, "app auth headers")
                    check(len(h["sign"]) == 32, "md5 sign length")

    text = st._extract_text({"status": True, "res": {"latex": "a^{2}-b^{2}", "conf": 0.9}})
    check(text == "a^{2}-b^{2}", "extract latex")
    text2 = st._extract_text({"status": True, "res": {"markdown": "答：42"}})
    check(text2 == "答：42", "extract markdown")
    check(st._extract_text({"status": True, "res": {"latex": "[EMPTY]"}}) == "", "empty token")
    # simpletex_ocr(general) 真实形态：type=formula + info
    text3 = st._extract_text({
        "status": True,
        "res": {"type": "formula", "info": "f(x)=x^{2}", "conf": 0.9},
    })
    check(text3 == "f(x)=x^{2}", "extract general res.info")


def test_ocr_image_mock() -> None:
    from deliver import simpletex as st

    with patch.object(st, "is_configured", return_value=True), \
         patch.object(st, "_cfg", return_value={
             "app_id": "", "app_secret": "", "uat": "uat-x",
             "base": "https://server.simpletex.cn", "mode": "general",
         }), \
         patch("deliver.simpletex.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": True, "res": {"markdown": "手写答案 x=1", "conf": 0.88}},
        )
        out = st.ocr_image(b"fakeimg", filename="a.jpg")
        check(out["ok"] is True, "ocr ok")
        check(out["text"] == "手写答案 x=1", "ocr text")
        check(mock_post.call_args.kwargs.get("proxies") == {"http": None, "https": None},
              "ocr direct no proxy")


def test_extract_richtext_and_ingest() -> None:
    from deliver.inbound_images import (
        extract_picture_download_codes,
        extract_rich_text_caption,
    )
    from deliver.dingtalk_bot import DingTalkHandler

    pic = {"msgtype": "picture", "content": {"downloadCode": "dc-pic"}}
    check(extract_picture_download_codes(pic) == ["dc-pic"], "picture downloadCode")

    rich = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "这是作答记录"},
                {"type": "picture", "downloadCode": "dc-rt"},
            ]
        },
    }
    check(extract_picture_download_codes(rich) == ["dc-rt"], "richText downloadCode")
    check(extract_rich_text_caption(rich) == "这是作答记录", "richText caption")

    bot = DingTalkHandler.__new__(DingTalkHandler)
    bot._get_credentials = lambda: ("cid", "csec")

    with tempfile.TemporaryDirectory() as td, \
         patch("deliver.inbound_images._ROOT", td), \
         patch("deliver.dingtalk_media.get_access_token", return_value="tok"), \
         patch("deliver.dingtalk_media.download_robot_file", return_value=b"imgbytes"):
        tip, ids = bot._ingest_dm_images(
            pic, "robot", "04022300566420984205", caption="这是作答"
        )
        check(bool(ids) and len(ids[0]) >= 8, "ingest returns image_id")
        check("grade_handwriting" in tip and "ocr_handwriting" in tip, "tip names cow tools")
        check("不要对无关" in tip, "tip warns against random screenshots")


def test_cow_tools_grade_handwriting() -> None:
    from learner.context import bind_learner
    from deliver import inbound_images as ii
    from agent import tools as T

    uid = "04022300566420984205"
    with tempfile.TemporaryDirectory() as td, \
         patch.object(ii, "_ROOT", td), \
         patch("deliver.simpletex.is_configured", return_value=True), \
         patch("deliver.simpletex.ocr_image", return_value={
             "ok": True, "text": "我的解答", "conf": 0.9, "raw": {}, "error": "", "mode": "general",
         }), \
         patch("agent.tools.grade_answer", return_value="[KP=极限] ✅ 正确，好") as mock_g:
        iid = ii.stash_image(uid, b"img", filename="a.jpg", caption="作答")
        with bind_learner(uid, binding="personal"):
            ocr = T.ocr_handwriting("")
            check(iid in ocr and "我的解答" in ocr, "ocr_handwriting uses latest")
            graded = T.grade_handwriting("")
            check("正确" in graded and "OCR" in graded, "grade_handwriting wraps grade")
            check(mock_g.call_args.args[1] == "我的解答", "grade user_answer is ocr text")

    from deliver.system_api import WHITELIST
    check("ocr_handwriting" in WHITELIST and "grade_handwriting" in WHITELIST, "whitelist")


def main() -> int:
    print("== simpletex / cow-image unit ==")
    test_sign_and_extract()
    test_ocr_image_mock()
    test_extract_richtext_and_ingest()
    test_cow_tools_grade_handwriting()
    print("=" * 40)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL SIMPLETEX TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
