"""钉钉媒体上传与图片/文件消息发送。"""
from __future__ import annotations

import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_access_token(client_id: str, client_secret: str) -> str:
    r = requests.post(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        json={"appKey": client_id, "appSecret": client_secret},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("accessToken", "") or ""


def upload_image(access_token: str, png_bytes: bytes, filename: str = "formula.png") -> str:
    """上传图片，返回 media_id；失败返回空串。"""
    if not access_token or not png_bytes:
        return ""
    try:
        r = requests.post(
            f"https://oapi.dingtalk.com/media/upload?access_token={access_token}",
            files={"media": (filename, png_bytes, "image/png")},
            data={"type": "image"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.ok and data.get("media_id"):
            return str(data["media_id"])
        logger.warning("media upload failed: %s %s", r.status_code, str(data)[:200])
    except Exception as e:
        logger.warning("media upload error: %s", e)
    return ""


def upload_file(
    access_token: str,
    file_bytes: bytes,
    filename: str,
    *,
    file_type: str = "file",
) -> str:
    """上传普通文件，返回 media_id。"""
    if not access_token or not file_bytes:
        return ""
    try:
        r = requests.post(
            f"https://oapi.dingtalk.com/media/upload?access_token={access_token}",
            files={"media": (filename, file_bytes, "application/octet-stream")},
            data={"type": file_type},
            timeout=60,
        )
        data = r.json() if r.content else {}
        if r.ok and data.get("media_id"):
            return str(data["media_id"])
        logger.warning("file upload failed: %s %s", r.status_code, str(data)[:200])
    except Exception as e:
        logger.warning("file upload error: %s", e)
    return ""


def send_oto_message(
    *,
    access_token: str,
    robot_code: str,
    user_ids: list[str],
    msg_key: str,
    msg_param: dict,
) -> bool:
    """人与机器人单聊：oToMessages/batchSend。"""
    ids = [u for u in (user_ids or []) if u]
    if not access_token or not robot_code or not ids:
        return False
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": access_token,
    }
    body = {
        "robotCode": robot_code,
        "userIds": ids[:20],
        "msgKey": msg_key,
        "msgParam": json.dumps(msg_param, ensure_ascii=False),
    }
    try:
        r = requests.post(
            "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
            headers=headers,
            json=body,
            timeout=15,
        )
        if r.ok:
            return True
        logger.error("oToMessages send failed: %s %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.error("oToMessages send error: %s", e)
    return False


def send_oto_markdown(
    *,
    access_token: str,
    robot_code: str,
    user_id: str,
    title: str,
    text: str,
) -> bool:
    return send_oto_message(
        access_token=access_token,
        robot_code=robot_code,
        user_ids=[user_id],
        msg_key="sampleMarkdown",
        msg_param={"title": (title or "瑞贝卡")[:30], "text": text},
    )


def send_group_message(
    *,
    access_token: str,
    robot_code: str,
    open_conversation_id: str,
    msg_key: str,
    msg_param: dict,
) -> bool:
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": access_token,
    }
    body = {
        "robotCode": robot_code,
        "openConversationId": open_conversation_id,
        "msgKey": msg_key,
        "msgParam": json.dumps(msg_param, ensure_ascii=False),
    }
    try:
        r = requests.post(
            "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
            headers=headers,
            json=body,
            timeout=15,
        )
        if r.ok:
            return True
        logger.error("groupMessages send failed: %s %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.error("groupMessages send error: %s", e)
    return False


def send_group_image(
    *,
    access_token: str,
    robot_code: str,
    open_conversation_id: str,
    media_id: str,
) -> bool:
    """sampleImageMsg：photoURL 可填 media_id（钉钉客户端内解析）。"""
    return send_group_message(
        access_token=access_token,
        robot_code=robot_code,
        open_conversation_id=open_conversation_id,
        msg_key="sampleImageMsg",
        msg_param={"photoURL": media_id},
    )


def send_group_file(
    *,
    access_token: str,
    robot_code: str,
    open_conversation_id: str,
    media_id: str,
    file_name: str,
    file_type: str,
) -> bool:
    return send_group_message(
        access_token=access_token,
        robot_code=robot_code,
        open_conversation_id=open_conversation_id,
        msg_key="sampleFile",
        msg_param={
            "mediaId": media_id,
            "fileName": file_name,
            "fileType": file_type,
        },
    )


def send_session_image(session_webhook: str, media_id: str) -> bool:
    """被动回复：sessionWebhook 发 image。"""
    if not session_webhook or not media_id:
        return False
    try:
        r = requests.post(
            session_webhook,
            json={"msgtype": "image", "image": {"media_id": media_id}},
            timeout=10,
        )
        body = (r.text or "")[:200]
        try:
            data = r.json()
        except Exception:
            data = {}
        err = data.get("errcode", 0) if isinstance(data, dict) else 0
        if r.ok and err in (0, None):
            return True
        logger.warning("session image failed: %s %s", r.status_code, body)
    except Exception as e:
        logger.warning("session image error: %s", e)
    return False


def send_session_markdown(session_webhook: str, title: str, text: str) -> bool:
    if not session_webhook or not text:
        return False
    try:
        r = requests.post(
            session_webhook,
            json={
                "msgtype": "markdown",
                "markdown": {"title": (title or "瑞贝卡")[:30], "text": text},
            },
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


def download_robot_file(
    access_token: str,
    download_code: str,
    robot_code: str,
) -> bytes:
    """下载机器人收到的文件（人机单聊 file 消息的 downloadCode）。

    文档：机器人接收消息文件内容下载。
    """
    if not access_token or not download_code or not robot_code:
        return b""
    try:
        r = requests.post(
            "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={"downloadCode": download_code, "robotCode": robot_code},
            timeout=30,
        )
        data = r.json() if r.content else {}
        url = ""
        if isinstance(data, dict):
            url = (
                data.get("downloadUrl")
                or data.get("url")
                or (data.get("result") or {}).get("downloadUrl")
                or ""
            )
        if not url:
            logger.warning("file download meta fail: %s %s", r.status_code, str(data)[:300])
            return b""
        fr = requests.get(url, timeout=60)
        if fr.ok:
            return fr.content or b""
        logger.warning("file download body fail: %s", fr.status_code)
    except Exception as e:
        logger.warning("file download error: %s", e)
    return b""


def send_group_action_card(
    *,
    access_token: str,
    robot_code: str,
    open_conversation_id: str,
    title: str,
    text: str,
    buttons: list,
) -> bool:
    """群主动推送 ActionCard（按钮 dtmd 回传文案）。"""
    from deliver.action_cards import build_group_action_param

    msg_key, msg_param = build_group_action_param(title, text, buttons)
    return send_group_message(
        access_token=access_token,
        robot_code=robot_code,
        open_conversation_id=open_conversation_id,
        msg_key=msg_key,
        msg_param=msg_param,
    )


def send_group_action_card_urls(
    *,
    access_token: str,
    robot_code: str,
    open_conversation_id: str,
    title: str,
    text: str,
    buttons: list,
) -> bool:
    """群主动推送 ActionCard；buttons=[(标题, https/dtmd URL), ...]。"""
    from deliver.action_cards import build_group_action_param_urls

    msg_key, msg_param = build_group_action_param_urls(title, text, buttons)
    return send_group_message(
        access_token=access_token,
        robot_code=robot_code,
        open_conversation_id=open_conversation_id,
        msg_key=msg_key,
        msg_param=msg_param,
    )



def send_session_action_card(
    session_webhook: str,
    title: str,
    text: str,
    buttons: list,
    *,
    btn_orientation: str = "0",
) -> bool:
    """被动回复：sessionWebhook 发 ActionCard。"""
    if not session_webhook or not buttons:
        return False
    from deliver.action_cards import build_session_action_card

    payload = build_session_action_card(
        title, text, buttons, btn_orientation=btn_orientation
    )
    try:
        r = requests.post(session_webhook, json=payload, timeout=10)
        if r.ok:
            return True
        logger.warning("session actionCard failed: %s %s", r.status_code, (r.text or "")[:200])
    except Exception as e:
        logger.warning("session actionCard error: %s", e)
    return False
