"""通知发送器 — 钉钉 webhook / 桥接。

设计上 sender 不关心消息内容是什么，只管发送。
"""
from __future__ import annotations

import json
import logging
from typing import Callable

import requests

logger = logging.getLogger(__name__)

# 各渠道单条消息字节上限
_CHANNEL_LIMITS = {
    "dingtalk": 20000,
    "telegram": 4000,
    "wecom": 4096,
    "stdout": 10_000_000,  # 不限
}


def send_trending(
    text: str,
    channel: str = "dingtalk",
    webhook_url: str = "",
    bridge_send: Callable[[str], None] | None = None,
) -> bool:
    """发送格式化后的 Trending 消息。

    Args:
        text: 格式化后的消息文本
        channel: 目标渠道
        webhook_url: 钉钉/企微 webhook URL（bridge_send 为空时使用）
        bridge_send: 外部发送函数（如 DingTalkPushBridge.send），
                     传此参数时忽略 webhook_url

    Returns:
        是否全部发送成功
    """
    if bridge_send is not None:
        return _send_via_bridge(text, bridge_send, channel)

    if channel == "stdout":
        print(text)
        return True

    if channel in ("dingtalk", "wecom"):
        return _send_webhook(text, webhook_url, channel)

    logger.warning(f"不支持的渠道: {channel}")
    return False


def _send_via_bridge(text: str, bridge_send: Callable[[str], None], channel: str) -> bool:
    """通过外部桥接函数发送。"""
    limit = _CHANNEL_LIMITS.get(channel, 20000)
    chunks = _split_message(text, limit)
    all_ok = True
    for chunk in chunks:
        try:
            bridge_send(chunk)
        except Exception as e:
            logger.error(f"bridge send 失败: {e}")
            all_ok = False
    return all_ok


def _send_webhook(text: str, webhook_url: str, channel: str) -> bool:
    """通过 webhook URL 直接 POST。"""
    if not webhook_url:
        logger.error(f"webhook_url 为空，无法发送 {channel}")
        return False

    limit = _CHANNEL_LIMITS.get(channel, 20000)
    chunks = _split_message(text, limit)
    all_ok = True

    for chunk in chunks:
        if channel == "dingtalk":
            payload = {"msgtype": "markdown", "markdown": {"title": "GitHub 今日热门", "text": chunk}}
        elif channel == "wecom":
            payload = {"msgtype": "markdown", "markdown": {"content": chunk}}
        else:
            payload = {"text": chunk}

        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"webhook 发送失败 ({channel}): {e}")
            all_ok = False

    return all_ok


def _split_message(text: str, max_bytes: int) -> list[str]:
    """按字节数切割长消息，尽量在换行处切。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return [text]

    chunks: list[str] = []
    pos = 0
    while pos < len(text):
        # 找到不超过 max_bytes 的切割点
        end = pos + max_bytes
        if end >= len(text):
            chunks.append(text[pos:])
            break

        # 尽量在换行处切
        slice_end = text.rfind("\n", pos, end)
        if slice_end <= pos:
            slice_end = end
        else:
            slice_end += 1  # 保留换行符给下一段

        chunks.append(text[pos:slice_end])
        pos = slice_end

    return chunks
