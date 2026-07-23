"""钉钉 ActionCard 构建 — 按钮用 dtmd 协议回传固定文案给机器人。

点击按钮 → 客户端向会话发送 content 文本 → Stream 收到 → Agent 处理。
无需互动卡片模板 / callback topic。
"""
from __future__ import annotations

from typing import Sequence
from urllib.parse import quote


def dtmd_send(content: str) -> str:
    """生成 dtmd://dingtalkclient/sendMessage?content=…"""
    return f"dtmd://dingtalkclient/sendMessage?content={quote(content, safe='')}"


# ── 出题后快捷按钮（文案须与 Agent SYSTEM_PROMPT 示例一致）──

QUESTION_ACTIONS: list[tuple[str, str]] = [
    ("我不会", "我不会做"),
    ("换一道", "换一道同类题"),
    ("太难了", "太难了"),
    ("要解析", "要解析"),
]

WEEKLY_ACTIONS: list[tuple[str, str]] = [
    ("出数学题", "出一道数学题巩固"),
    ("出通信题", "出一道通信题巩固"),
    ("看指标", "我现在水平怎么样"),
]


def _pick_msg_key(n: int) -> str:
    """企业机器人模板：sampleActionCard2–5 竖排多按钮；6 为横排两按钮。"""
    if n <= 1:
        return "sampleActionCard"
    if n == 2:
        return "sampleActionCard2"
    if n == 3:
        return "sampleActionCard3"
    if n == 4:
        return "sampleActionCard4"
    return "sampleActionCard5"


def build_group_action_param(
    title: str,
    text: str,
    buttons: Sequence[tuple[str, str]],
) -> tuple[str, dict]:
    """返回 (msgKey, msgParam) 供 groupMessages/send。

    buttons: [(按钮标题, 点击后发送的文本), ...]
    """
    btns = list(buttons)[:5]
    n = len(btns)
    if n == 0:
        raise ValueError("ActionCard 至少需要 1 个按钮")

    msg_key = _pick_msg_key(n)
    param: dict = {
        "title": (title or "快捷操作")[:64],
        "text": text or "请选择：",
    }

    if n == 1:
        label, content = btns[0]
        param["singleTitle"] = label[:20]
        param["singleURL"] = dtmd_send(content)
        return msg_key, param

    for i, (label, content) in enumerate(btns, start=1):
        param[f"actionTitle{i}"] = label[:20]
        param[f"actionURL{i}"] = dtmd_send(content)
    return msg_key, param


def build_session_action_card(
    title: str,
    text: str,
    buttons: Sequence[tuple[str, str]],
    *,
    btn_orientation: str = "0",
) -> dict:
    """sessionWebhook 用的 actionCard payload。"""
    btns = [
        {"title": label[:20], "actionURL": dtmd_send(content)}
        for label, content in list(buttons)[:5]
    ]
    return {
        "msgtype": "actionCard",
        "actionCard": {
            "title": (title or "快捷操作")[:64],
            "text": text or "请选择：",
            "btnOrientation": btn_orientation,
            "btns": btns,
        },
    }


def question_card_text(subject: str = "") -> str:
    subj = {"math": "数学", "comm": "通信", "review": "复盘"}.get(subject, "")
    head = f"**{subj}题已推送**" if subj else "**题目已就绪**"
    return (
        f"{head}\n\n"
        "做完直接打字交答案；也可以点下面按钮：\n"
        "- **我不会** / **要解析** → 看解答\n"
        "- **换一道** → 同类再来一题\n"
        "- **太难了** → 下调难度"
    )


def weekly_card_title() -> str:
    return "本周学习周报"


def question_followup_hint() -> str:
    return "题目在上方。点按钮或直接作答均可。"
