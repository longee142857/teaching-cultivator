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

    buttons: [(按钮标题, 点击后发送的文本), ...] — URL 为 dtmd 回传。
    """
    return build_group_action_param_urls(
        title,
        text,
        [(label, dtmd_send(content)) for label, content in buttons],
    )


def build_group_action_param_urls(
    title: str,
    text: str,
    buttons: Sequence[tuple[str, str]],
) -> tuple[str, dict]:
    """返回 (msgKey, msgParam)；buttons 为 (标题, 完整 URL)，可为 https 或 dtmd。"""
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
        label, url = btns[0]
        param["singleTitle"] = label[:20]
        param["singleURL"] = url[:500]
        return msg_key, param

    for i, (label, url) in enumerate(btns, start=1):
        param[f"actionTitle{i}"] = label[:20]
        param[f"actionURL{i}"] = url[:500]
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


def question_card_text(subject: str = "", *, with_deep_link: bool = True) -> str:
    subj = {"math": "数学", "comm": "通信", "review": "复盘"}.get(subject, "")
    head = f"**{subj}题已推送**" if subj else "**题目已就绪**"
    if with_deep_link:
        return (
            f"{head}\n\n"
            "请点下方按钮打开练习台作答（本题不在聊天里作答）。\n"
            "讲解与批改结果也在前端查看。"
        )
    return f"{head}\n\n请打开练习台作答。题干不在聊天里发送。"


def practice_open_buttons(deep_link: str) -> list[tuple[str, str]]:
    """练习台深链按钮（https，非 dtmd）。"""
    url = (deep_link or "").strip()
    if not url.startswith("http"):
        raise ValueError("practice deep_link must be http(s)")
    return [("打开练习台", url)]


def weekly_card_title() -> str:
    return "本周学习周报"


def question_followup_hint() -> str:
    return "题目在上方。点按钮或直接作答均可。"


def confirm_kp_actions(token: str) -> list[tuple[str, str]]:
    """添加知识点确认卡的按钮（dtmd 回传文案，须与 agent._KP_CONFIRM_RE 匹配）。"""
    return [
        ("确认添加", f"确认添加知识点 {token}"),
        ("取消", f"取消添加知识点 {token}"),
    ]


def confirm_kp_title() -> str:
    return "添加知识点确认"


def confirm_kp_text() -> str:
    return (
        "只会在已有章节下追加子考点，不会新建章节。\n"
        "确认后即写入考纲，之后出题/双周卷可覆盖该子考点。"
    )


def confirm_override_actions(token: str) -> list[tuple[str, str]]:
    """批改纠正确认卡的按钮（dtmd 回传文案，须与 agent._OVERRIDE_CONFIRM_RE 匹配）。"""
    return [
        ("确认纠正", f"确认纠正 {token}"),
        ("取消", f"取消纠正 {token}"),
    ]


def confirm_override_title() -> str:
    return "批改纠正确认"


def confirm_override_text(kp: str = "", correct: bool | None = None) -> str:
    verdict = "判对" if correct is True else ("判错" if correct is False else "")
    kp_s = f"知识点「{kp}」" if kp else "该知识点"
    verdict_s = f"，纠正为{verdict}" if verdict else ""
    return (
        f"你请求纠正 {kp_s} 最近一次批改{verdict_s}。\n"
        "确认后会重算掌握度并写入审计记录；取消则不改变。"
    )
