"""企业微信 Bot — 基于已验证的 WebSocket 直连方案"""
from __future__ import annotations
import json, time, uuid, threading, requests, urllib3, sys, io, os
from websocket import create_connection

# Windows GBK 终端兼容：print 遇到 emoji 不炸
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_WX_LOG = None  # 外部设置的日志文件路径
_CHAT_ID_FILE = None  # 持久化 chat_id 的文件路径


def _log_to_file(msg: str):
    """写入 wecom_bot 内部日志（不依赖外部 log() 函数）。"""
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with open(_WX_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


class WecomBot:
    def __init__(self, bot_id: str, secret: str):
        self.bot_id = bot_id
        self.secret = secret
        self._ws = None
        self._alive = False
        self._response_url = ""
        self.chat_id = ""
        self.chat_type = 1
        self._load_chat_id()

    def _load_chat_id(self):
        """从持久化文件加载已保存的 chat_id（如有）。"""
        if not _CHAT_ID_FILE:
            return
        try:
            if os.path.exists(_CHAT_ID_FILE):
                with open(_CHAT_ID_FILE, "r") as f:
                    data = json.load(f)
                self.chat_id = data.get("chat_id", "")
                self.chat_type = data.get("chat_type", 1)
                if self.chat_id:
                    _log_to_file(f"[WX] 恢复持久化 chat_id={self.chat_id[:12]}...")
        except Exception as e:
            _log_to_file(f"[WX] chat_id 加载失败: {e}")

    def _save_chat_id(self):
        """持久化 chat_id 到文件，重连后可恢复。"""
        if not _CHAT_ID_FILE:
            return
        try:
            os.makedirs(os.path.dirname(_CHAT_ID_FILE), exist_ok=True)
            with open(_CHAT_ID_FILE, "w") as f:
                json.dump({"chat_id": self.chat_id, "chat_type": self.chat_type}, f)
        except Exception as e:
            _log_to_file(f"[WX] chat_id 保存失败: {e}")

    def on_message(self, body: dict):
        pass

    def reply(self, text: str) -> bool:
        """回复当前对话（走 response_url，只能回复最近一条消息）。"""
        if not self._response_url:
            return False
        try:
            resp = requests.post(self._response_url,
                json={"msgtype": "markdown", "markdown": {"content": text}},
                timeout=10, verify=False)
            return resp.ok and resp.json().get("errcode") == 0
        except:
            return False

    def send_push(self, chat_id: str, text: str) -> bool:
        """通过 WebSocket 主动推送消息到指定对话。

        需要先从 aibot_msg_callback 得到 chat_id（用户至少发过一条消息）。
        频率限制：30条/分钟，1000条/小时（与回复共享配额）。
        """
        if not self._ws:
            _log_to_file(f"[WX] send_push skipped: ws is None")
            return False
        if not chat_id:
            _log_to_file(f"[WX] send_push skipped: chat_id is empty（用户未发过消息）")
            return False
        try:
            self._ws.send(json.dumps({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": uuid.uuid4().hex[:12]},
                "body": {
                    "chatid": chat_id,
                    "chat_type": 1,
                    "msgtype": "markdown",
                    "markdown": {"content": text},
                },
            }))
            _log_to_file(f"[WX] send_push sent OK (chat_id={chat_id[:12]}...)")
            return True
        except Exception as e:
            _log_to_file(f"[WX] send_push exception: {e}")
            print(f"[WX] send_push failed: {e}", flush=True)
            return False

    def start(self):
        self._alive = True
        while self._alive:
            try:
                self._run()
            except Exception as e:
                print(f"[WX] conn err: {e}", flush=True)
            time.sleep(5)

    def stop(self):
        self._alive = False
        if self._ws:
            try: self._ws.close()
            except: pass

    def _run(self):
        ws = create_connection("wss://openws.work.weixin.qq.com", timeout=10)
        self._ws = ws

        ws.send(json.dumps({"cmd": "aibot_subscribe",
            "headers": {"req_id": uuid.uuid4().hex[:12]},
            "body": {"bot_id": self.bot_id, "secret": self.secret}}))
        ws.settimeout(5)
        r = json.loads(ws.recv())
        if r.get("errcode") != 0:
            print(f"[WX] auth fail: {r}", flush=True)
            ws.close()
            return
        _log_to_file("[WX] ✅ WebSocket 已连接")
        print("[WX] ✅ 已连接", flush=True)

        # 收消息 + 内联心跳（避免独立线程断线后主循环无法感知）
        last_ping = time.time()
        ws.settimeout(30)
        while self._alive:
            try:
                raw = ws.recv()
            except:
                # 每 30 秒 recv 超时 → 检查是否需要发 ping
                now = time.time()
                if now - last_ping >= 25:
                    try:
                        ws.send(json.dumps({"cmd": "ping"}))
                        last_ping = now
                    except:
                        print("[WX] ping fail, reconnecting...", flush=True)
                        break  # 连接断了，让 _run() 退出，start() 重连
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except:
                continue
            cmd = msg.get("cmd", "")
            if cmd == "aibot_msg_callback":
                body = msg.get("body", {})
                self._response_url = body.get("response_url", "")
                _from = body.get("from", "")
                if isinstance(_from, dict):
                    self.chat_id = _from.get("userid", "") or _from.get("user_id", "")
                else:
                    self.chat_id = str(_from or "")
                self.chat_type = body.get("chattype", body.get("chat_type", 1))
                self._save_chat_id()
                # 诊断：任何回调都落盘，避免空正文静默丢失
                try:
                    mt = body.get("msgtype") or body.get("msg_type") or "?"
                    keys = ",".join(sorted(body.keys()))
                    preview = json.dumps(body, ensure_ascii=False)[:400]
                    _log_to_file(f"[WX] callback msgtype={mt} keys={keys} body={preview}")
                except Exception as e:
                    _log_to_file(f"[WX] callback log fail: {e}")
                self.on_message(body)
            elif cmd == "aibot_send_msg" and "errcode" in msg:
                ec = msg.get("errcode", -1)
                em = msg.get("errmsg", "")
                if ec != 0:
                    _log_to_file(f"[WX] send_msg FAIL: ec={ec} {em}")
            elif cmd == "pong":
                pass  # 心跳回复，忽略
            elif cmd:  # 其他已知命令不感兴趣
                pass
