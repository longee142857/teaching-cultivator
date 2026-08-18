"""通知模块 — 仅通知，不含答题/讲解。

产品约定：第三方 IM 只发「有新题 / 批改完成」等短通知 + 前端深链；
作答与讲解全部在前端完成。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol
from urllib.parse import urlencode


@dataclass
class Notification:
    """结构化通知（通道无关）。"""

    kind: str  # new_item | grade_ready | exam_ready | review_due
    learner_id: str
    title: str
    body: str
    deep_link: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def plain_text(self) -> str:
        if self.deep_link:
            return f"{self.title}\n{self.body}\n{self.deep_link}"
        return f"{self.title}\n{self.body}"


class NotifyChannel(Protocol):
    def send_notification(self, note: Notification) -> bool: ...


class StdoutNotify:
    def send_notification(self, note: Notification) -> bool:
        text = note.plain_text()
        if not text.strip():
            return False
        print(text)
        return True


def build_deep_link(
    base_url: str,
    *,
    path: str = "/practice",
    learner_id: str = "",
    item_id: Optional[int] = None,
    push_id: Optional[int] = None,
) -> str:
    """前端深链；base_url 由 env FRONTEND_BASE_URL 提供。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    q: dict[str, str] = {}
    if learner_id:
        q["learner"] = learner_id
    if item_id is not None:
        q["item"] = str(item_id)
    if push_id is not None:
        q["push"] = str(push_id)
    suffix = f"?{urlencode(q)}" if q else ""
    return f"{base}{path}{suffix}"


def notify_new_item(
    channel: NotifyChannel,
    *,
    learner_id: str,
    subject: str,
    item_id: Optional[int] = None,
    push_id: Optional[int] = None,
    frontend_base: str = "",
    kp: str = "",
) -> bool:
    link = build_deep_link(
        frontend_base,
        path="/practice",
        learner_id=learner_id,
        item_id=item_id,
        push_id=push_id,
    )
    kp_bit = f"「{kp}」" if kp else ""
    note = Notification(
        kind="new_item",
        learner_id=learner_id,
        title="新练习题已就绪",
        body=f"{subject}{kp_bit} — 请打开前端作答（本题不在聊天里作答）",
        deep_link=link,
        meta={"subject": subject, "item_id": item_id, "push_id": push_id, "kp": kp},
    )
    return channel.send_notification(note)


def get_default_channel() -> NotifyChannel:
    """兼容旧 DeliverBridge：优先 stdout；main 可注入钉钉/企微文本通知。"""
    return StdoutNotify()


__all__ = [
    "Notification",
    "NotifyChannel",
    "StdoutNotify",
    "build_deep_link",
    "get_default_channel",
    "notify_new_item",
]
