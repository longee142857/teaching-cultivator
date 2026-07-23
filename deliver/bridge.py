"""推送桥 — 可插拔：企业微信 webhook / stdout

cultivate.py 通过 get_bridge() 获取推送通道。
main.py 定时推送时 monkey-patch 为 bot.send_push 通道。
"""
from __future__ import annotations


class DeliverBridge:
    """推送桥基类。子类实现 send()。"""

    def send(self, content: str) -> bool:
        raise NotImplementedError

    def is_ready(self) -> bool:
        return True


class StdoutBridge(DeliverBridge):
    """打印到 stdout，由父进程捕获转发。"""
    def send(self, content: str) -> bool:
        if not content or not content.strip():
            return False
        print(content)
        return True


class WecomWebhookBridge(DeliverBridge):
    """企业微信群机器人 webhook（备用通道，不走 WebSocket）。"""
    def send(self, content: str) -> bool:
        from config import WECOM_WEBHOOK
        if not WECOM_WEBHOOK:
            return False
        import requests
        resp = requests.post(
            WECOM_WEBHOOK,
            json={"msgtype": "text", "text": {"content": content}},
            timeout=10,
        )
        return resp.ok

    def is_ready(self) -> bool:
        from config import WECOM_WEBHOOK
        return bool(WECOM_WEBHOOK)


def get_bridge() -> DeliverBridge:
    """返回可用的推送桥。优先 webhook，退化为 stdout。"""
    wc = WecomWebhookBridge()
    if wc.is_ready():
        return wc
    return StdoutBridge()
