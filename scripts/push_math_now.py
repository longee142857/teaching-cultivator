"""临时数学推送（联调）：走 WebSocket 主动推送到已保存的 chat_id。

用法:
    py -3 scripts/push_math_now.py

会短暂另建 WS（运行中的 main 可能掉线并自动重连）。
出题强制为 push/intermediate，避免 escalate/defer 跳过联调。
"""
from __future__ import annotations
import os, sys, json, time, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from config import WECOM_BOT_ID, WECOM_BOT_SECRET, DATA_DIR
from cultivate import generate, record, get_last_answer, _save_last_push
from intervention import InterventionDecision
import deliver.wecom_bot as wb
from deliver.wecom_bot import WecomBot
from websocket import create_connection


def _load_chat_id() -> tuple[str, int]:
    path = os.path.join(DATA_DIR, "chat_id.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("chat_type", 1)
    # 持久化里可能是 "single"/"group" 或数字
    if isinstance(raw, str):
        chat_type = 1 if raw.lower() in ("1", "single", "私聊", "") else 2
    else:
        chat_type = int(raw or 1)
    return data["chat_id"], chat_type


def send_via_ws(chat_id: str, chat_type: int, text: str) -> bool:
    wb._WX_LOG = os.path.join(DATA_DIR, "logs", "listener.log")
    ws = create_connection("wss://openws.work.weixin.qq.com", timeout=15)
    try:
        ws.send(json.dumps({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": uuid.uuid4().hex[:12]},
            "body": {"bot_id": WECOM_BOT_ID, "secret": WECOM_BOT_SECRET},
        }))
        ws.settimeout(10)
        auth = json.loads(ws.recv())
        if auth.get("errcode") != 0:
            print(f"[push_now] auth fail: {auth}")
            return False
        print("[push_now] WS auth OK")
        ws.send(json.dumps({
            "cmd": "aibot_send_msg",
            "headers": {"req_id": uuid.uuid4().hex[:12]},
            "body": {
                "chatid": chat_id,
                "chat_type": chat_type,
                "msgtype": "markdown",
                "markdown": {"content": text},
            },
        }))
        # 尽量读一条回执
        try:
            ws.settimeout(5)
            ack = json.loads(ws.recv())
            print(f"[push_now] ack: errcode={ack.get('errcode')} errmsg={ack.get('errmsg', '')}")
            if ack.get("cmd") == "aibot_send_msg" and ack.get("errcode", 0) != 0:
                return False
        except Exception as e:
            print(f"[push_now] no ack (may still be delivered): {e}")
        return True
    finally:
        try:
            ws.close()
        except Exception:
            pass


def main() -> int:
    chat_id, chat_type = _load_chat_id()
    print(f"[push_now] chat_id={chat_id} type={chat_type}")

    decision = InterventionDecision(
        "push", "intermediate", "临时联调: 数学一出题", 3
    )
    print("[push_now] generating...")
    content = generate("math", decision)
    answer = get_last_answer()
    if not content:
        print("[push_now] generate empty")
        return 1

    record("math", content, decision, answer)
    _save_last_push("math", decision, content, answer)

    preview = content[:200].replace("\n", " ")
    print(f"[push_now] question preview: {preview}...")
    print(f"[push_now] answer cached len={len(answer)}")

    ok = send_via_ws(chat_id, chat_type, content)
    print(f"[push_now] deliver={'OK' if ok else 'FAIL'}")
    print("[push_now] 请在企微作答；Bot 主进程若掉线会自动重连。")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
