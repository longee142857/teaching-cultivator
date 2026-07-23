"""ActionCard 构建单元测试（不调钉钉 API）。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deliver.action_cards import (
    QUESTION_ACTIONS,
    WEEKLY_ACTIONS,
    build_group_action_param,
    build_session_action_card,
    dtmd_send,
    question_card_text,
)


def test_dtmd_encodes_chinese():
    url = dtmd_send("我不会做")
    assert url.startswith("dtmd://dingtalkclient/sendMessage?content=")
    assert "我不会做" not in url  # must be percent-encoded
    assert "%E6%88%91" in url or "%e6%88%91" in url.lower()
    print("OK dtmd encodes")


def test_group_param_four_buttons():
    key, param = build_group_action_param(
        "快捷操作", question_card_text("math"), QUESTION_ACTIONS
    )
    assert key == "sampleActionCard4"
    assert param["actionTitle1"] == "我不会"
    assert param["actionURL1"].startswith("dtmd://")
    assert param["actionTitle4"] == "要解析"
    assert "actionTitle5" not in param
    print("OK group sampleActionCard4")


def test_group_param_three_buttons():
    key, param = build_group_action_param("周报", "正文", WEEKLY_ACTIONS)
    assert key == "sampleActionCard3"
    assert len([k for k in param if k.startswith("actionTitle")]) == 3
    print("OK group sampleActionCard3")


def test_session_payload():
    payload = build_session_action_card("快捷", "选一个", QUESTION_ACTIONS)
    assert payload["msgtype"] == "actionCard"
    card = payload["actionCard"]
    assert len(card["btns"]) == 4
    assert card["btns"][0]["title"] == "我不会"
    assert "dtmd://" in card["btns"][0]["actionURL"]
    print("OK session actionCard")


if __name__ == "__main__":
    test_dtmd_encodes_chinese()
    test_group_param_four_buttons()
    test_group_param_three_buttons()
    test_session_payload()
    print("ALL PASS")
