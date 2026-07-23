"""微信桥 — ilink bot 协议封装

过渡期微信桥（主通道已为企业微信 Bot）。
"""
from __future__ import annotations
import json, os, uuid, time, tempfile
import requests, urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_session = requests.Session()
_session.verify = False

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
BOT_TYPE = "3"
QR_LOGIN_TIMEOUT_S = 120
QR_MAX_REFRESHES = 5


class WechatBridge:
    """微信桥：读凭证 → 收发消息 → 扫码重登。"""

    def __init__(self, cred_path: str = ""):
        self.cred_path = cred_path or os.path.expanduser(
            "~/.weixin_cow_teacher_credentials.json"
        )
        self.base_url: str = DEFAULT_BASE_URL
        self.token: str = ""
        self.bot_id: str = ""
        self.user_id: str = ""
        self.context_tokens: dict[str, str] = {}
        self._load_creds()

    # ── 凭证 ──────────────────────────────────────────────

    def _load_creds(self) -> bool:
        try:
            with open(self.cred_path, "r") as f:
                d = json.load(f)
            self.token = d.get("token", "")
            self.base_url = d.get("base_url", DEFAULT_BASE_URL)
            self.bot_id = d.get("bot_id", "")
            self.user_id = d.get("user_id", "")
            self.context_tokens = d.get("context_tokens", {})
            return bool(self.token)
        except Exception:
            return False

    def _save_creds(self):
        os.makedirs(os.path.dirname(self.cred_path), exist_ok=True)
        d = {
            "token": self.token,
            "base_url": self.base_url,
            "bot_id": self.bot_id,
            "user_id": self.user_id,
            "context_tokens": self.context_tokens,
        }
        tmp = self.cred_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.cred_path)

    @property
    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.token}",
            "X-WECHAT-UIN": "dGVzdA==",
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": "131072",
        }

    # ── 发消息 ──────────────────────────────────────────────

    def send_text(self, to: str, text: str) -> bool:
        ctx_token = self.context_tokens.get(to, "") or self.context_tokens.get(self.user_id, "")
        if not ctx_token:
            return False
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to,
                "client_id": uuid.uuid4().hex[:16],
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
                "context_token": ctx_token,
            }
        }
        try:
            r = _session.post(f"{self.base_url}/ilink/bot/sendmessage",
                              headers=self._headers, json=body, timeout=10)
            return r.ok
        except Exception as e:
            print(f"[wx] send error: {e}")
            return False

    def send_to_user(self, text: str) -> bool:
        return self.send_text(self.user_id, text)

    # ── 收消息 ──────────────────────────────────────────────

    def get_updates(self, timeout: int = 25) -> list:
        body = {"bot_id": self.bot_id, "timeout": timeout}
        try:
            r = _session.post(f"{self.base_url}/ilink/bot/getupdates",
                              headers=self._headers, json=body, timeout=timeout + 5)
            if r.ok:
                data = r.json()
                if data.get("ret") == 0:
                    for msg in data.get("data", []):
                        uid = msg.get("from_user_id", "")
                        ctx = msg.get("context_token", "")
                        if uid and ctx:
                            self.context_tokens[uid] = ctx
                    return data.get("data", [])
            return []
        except Exception:
            return []

    # ── 扫码登录 ──────────────────────────────────────────

    def fetch_qr_code(self) -> dict:
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
        r = _session.get(url, timeout=15)
        r.raise_for_status()
        return r.json()

    def poll_qr_status(self, qrcode: str, timeout: int = 35) -> dict:
        from requests.utils import quote
        url = f"{self.base_url}/ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        try:
            r = _session.get(url, headers={"iLink-App-Id": "bot",
                                            "iLink-App-ClientVersion": "131072"},
                             timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            return {"status": "wait"}

    def login_interactive(self) -> bool:
        """交互式扫码登录。返回 True 表示登录成功。"""
        api = WechatBridge.__new__(WechatBridge)
        api.base_url = self.base_url
        api.token = ""

        try:
            qr_resp = api.fetch_qr_code()
        except Exception as e:
            print(f"[wx] 获取二维码失败: {e}")
            return False

        qrcode = qr_resp.get("qrcode", "")
        qrcode_url = qr_resp.get("qrcode_img_content", "")
        if not qrcode:
            print("[wx] 二维码数据为空")
            return False

        # 显示二维码
        print(f"\n{'='*50}")
        print("  微信扫码登录教学助理")
        print(f"{'='*50}")
        print(f"  二维码图片: {self._save_qr_img(qrcode_url)}")
        print(f"  二维码链接: {qrcode_url}")
        print("  等待扫码（用微信扫上面的二维码）...\n")

        deadline = time.time() + QR_LOGIN_TIMEOUT_S
        refresh_count = 0
        scanned = False

        while time.time() < deadline:
            status_resp = api.poll_qr_status(qrcode)
            status = status_resp.get("status", "wait")

            if status == "scaned" and not scanned:
                scanned = True
                print("  已扫码，请在手机上确认...")
            elif status == "confirmed":
                self.token = status_resp.get("bot_token", "")
                self.bot_id = status_resp.get("ilink_bot_id", "")
                self.user_id = status_resp.get("ilink_user_id", "")
                url = status_resp.get("baseurl", self.base_url)
                if url:
                    self.base_url = url
                if not self.token or not self.bot_id:
                    print("[wx] 登录确认但缺少 token/bot_id")
                    return False
                print(f"  ✅ 登录成功！bot_id={self.bot_id}")
                self._save_creds()
                return True
            elif status == "expired":
                refresh_count += 1
                if refresh_count >= QR_MAX_REFRESHES:
                    print("[wx] 二维码刷新次数过多")
                    return False
                print("  二维码过期，刷新中...")
                try:
                    qr_resp = api.fetch_qr_code()
                    qrcode = qr_resp.get("qrcode", "")
                    qrcode_url = qr_resp.get("qrcode_img_content", "")
                    self._save_qr_img(qrcode_url)
                except Exception as e:
                    print(f"[wx] 刷新失败: {e}")
                    return False
                scanned = False

            time.sleep(1)

        print("[wx] 登录超时")
        return False

    @staticmethod
    def _save_qr_img(url: str) -> str:
        """把二维码图片存成文件，返回路径。"""
        try:
            r = _session.get(url, timeout=10)
            path = os.path.join(tempfile.gettempdir(), "wx_qrcode.png")
            with open(path, "wb") as f:
                f.write(r.content)
            return path
        except Exception:
            return url

    def is_ready(self) -> bool:
        return bool(self.token) and bool(self.bot_id)
