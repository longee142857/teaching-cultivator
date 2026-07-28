"""钉钉 Stream Mode Bot — 替代企业微信 WebSocket Bot

依赖: pip install dingtalk-stream requests matplotlib pillow

架构:
  DingTalkHandler — Stream SDK handler, 接收消息 → agent.handle → reply_markdown
                   + 公式 PNG（sessionWebhook image）
  DingTalkBot     — 管理 Stream 客户端生命周期 + conversation_id 持久化
  DingTalkPushBridge — 主动推送桥（OpenAPI），给 scheduler 用
"""
from __future__ import annotations
import asyncio, json, os, socket, threading, time, logging
from typing import Callable, Optional

# Fix: 钉钉 IPv6 不可达，强制 Python 全栈只用 IPv4
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: \
    _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

import requests
import dingtalk_stream
from dingtalk_stream import AckMessage

logger = logging.getLogger(__name__)

# ── 消息去重（BIG-TEACH-012c #8b）──
_INBOUND_DEDUP_TTL = 600  # 秒
_INBOUND_DEDUP_MAX = 4096


class _InboundDedup:
    """钉钉 Stream 重投去重（inbound msgId TTL cache）。

    Stream 长耗时未及时 ACK 会重投同一 msgId；超过 TTL 自动过期。
    """
    def __init__(self, ttl: int = _INBOUND_DEDUP_TTL, max_size: int = _INBOUND_DEDUP_MAX):
        self._ttl = ttl
        self._max_size = max_size
        self._seen: dict[str, float] = {}

    def claim(self, msg_id: str) -> bool:
        """尝试认领 msgId。若已存在且未过期则返回 False（重复），否则 True（新消息）。"""
        if not msg_id:
            return True
        now = time.time()
        # 惰性清理过期
        stale = [k for k, ts in self._seen.items() if now - ts > self._ttl]
        for k in stale:
            self._seen.pop(k, None)
        # 容量保护（超过上限时清一半最旧的）
        if len(self._seen) >= self._max_size:
            sorted_by_ts = sorted(self._seen.items(), key=lambda x: x[1])
            for k, _ in sorted_by_ts[:len(sorted_by_ts) // 2]:
                self._seen.pop(k, None)
        if msg_id in self._seen:
            return False
        self._seen[msg_id] = now
        return True

    def make_fingerprint(self, conversation_id: str, text: str, staff_id: str = "") -> str:
        """无 msgId 时的 fallback：学员+会话+文本简短指纹。"""
        import hashlib
        raw = f"{staff_id}|{conversation_id}|{text}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def claim_by_fingerprint(self, conversation_id: str, text: str, staff_id: str = "") -> bool:
        """用指纹去重。"""
        fp = self.make_fingerprint(conversation_id, text, staff_id)
        return self.claim(fp)


# 全局去重实例（单 bot 进程内有效）
_INBOUND_DEDUP = _InboundDedup()

# 单条回复最多跟发公式图数量（防刷屏）
MAX_FORMULA_IMAGES = 6


def _send_session_webhook(session_webhook: str, text: str, *, title: str = "瑞贝卡") -> bool:
    """向钉钉 sessionWebhook 发一条短消息（中间态用）。"""
    if not session_webhook or not text:
        return False
    try:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title[:30] or "瑞贝卡",
                "text": text[:500],
            },
        }
        r = requests.post(session_webhook, json=payload, timeout=8)
        if not r.ok:
            logger.warning("session_webhook interim failed: %s %s", r.status_code, r.text[:120])
            return False
        return True
    except Exception as e:
        logger.warning("session_webhook interim error: %s", e)
        return False


def _deliver_formula_images_session(
    session_webhook: str,
    client_id: str,
    client_secret: str,
    pieces: list,
) -> int:
    """渲染并经 sessionWebhook 发送公式图，返回成功张数。"""
    if not session_webhook or not pieces:
        return 0
    try:
        from deliver.latex_render import render_pieces
        from deliver.dingtalk_media import get_access_token, upload_image, send_session_image
    except Exception as e:
        logger.warning("formula deps missing: %s", e)
        return 0

    rendered = render_pieces(pieces[:MAX_FORMULA_IMAGES])
    if not rendered:
        return 0
    try:
        token = get_access_token(client_id, client_secret)
    except Exception as e:
        logger.warning("token for formula upload failed: %s", e)
        return 0
    if not token:
        return 0

    ok_n = 0
    for piece, png in rendered:
        mid = upload_image(token, png, filename=f"{piece.placeholder}.png")
        if mid and send_session_image(session_webhook, mid):
            ok_n += 1
            logger.info("session formula image ok: %s", piece.placeholder)
        else:
            logger.warning("session formula image failed: %s", piece.placeholder)
    return ok_n


class DingTalkHandler(dingtalk_stream.ChatbotHandler):
    """接收到钉钉消息 → 调 Agent → 回复（同 conversation 串行）。"""

    def __init__(
        self,
        agent_getter: Callable,
        conversation_saver: Callable[[str], None],
        credentials_getter: Optional[Callable[[], tuple[str, str]]] = None,
    ):
        super().__init__()
        self._get_agent = agent_getter
        self._save_conversation = conversation_saver
        self._get_credentials = credentials_getter
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_mu = threading.Lock()

    async def _lock_for(self, conv_id: str) -> asyncio.Lock:
        key = conv_id or "_default"
        with self._locks_mu:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    def _handle_exam_file(self, raw: dict, robot_code: str) -> str:
        """人机单聊收到 file → 下载 md → 批改双周答卷。"""
        content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        # 兼容不同 SDK 字段位置
        if not content:
            content = raw
        download_code = (
            content.get("downloadCode")
            or raw.get("downloadCode")
            or ""
        )
        file_name = content.get("fileName") or raw.get("fileName") or "answer.md"
        if not download_code:
            return "未拿到文件下载码。请在人机单聊中发送 .md 答卷文件。"
        if not str(file_name).lower().endswith((".md", ".markdown", ".txt")):
            return f"暂只接受 .md / .txt 答卷，收到的是：{file_name}"
        from deliver.dingtalk_media import get_access_token, download_robot_file

        if not self._get_credentials:
            return "机器人凭证不可用，无法下载文件。"
        client_id, client_secret = self._get_credentials()
        token = get_access_token(client_id, client_secret)
        rc = robot_code or client_id
        data = download_robot_file(token, download_code, rc)
        if not data:
            return "下载答卷文件失败。请改用：私聊发送文本，首行写「交卷」后粘贴 Markdown。"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        from learner.biweekly_exam import submit_answer_md

        return submit_answer_md(text)

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        raw = callback.data if isinstance(callback.data, dict) else {}

        # ── inbound 去重（BIG-TEACH-012c #8b）：重投直接 ACK ──
        global _INBOUND_DEDUP
        msg_id = raw.get("msgId", "") or ""
        text_early = " ".join(msg.get_text_list() or [])
        sender_staff_early = (
            getattr(msg, "sender_staff_id", None)
            or raw.get("senderStaffId", "")
            or ""
        )
        conv_early = (
            raw.get("openConversationId", "")
            or raw.get("conversationId", "")
            or getattr(msg, "conversation_id", "")
            or ""
        )
        if msg_id:
            if not _INBOUND_DEDUP.claim(msg_id):
                logger.info("dedup: skip duplicate msgId=%s", msg_id[:20])
                return AckMessage.STATUS_OK, "OK"
        elif text_early.strip():
            if not _INBOUND_DEDUP.claim_by_fingerprint(
                conv_early, text_early.strip(), sender_staff_early
            ):
                logger.info(
                    "dedup: skip duplicate fingerprint staff=%s text=%s",
                    (sender_staff_early[:8] + "…") if sender_staff_early else "-",
                    text_early[:40],
                )
                return AckMessage.STATUS_OK, "OK"
        text = text_early
        sw = getattr(msg, "session_webhook", None)
        robot_code = raw.get("robotCode", "") or ""
        sender_staff = sender_staff_early
        sender_nick = getattr(msg, "sender_nick", None) or raw.get("senderNick", "") or ""
        # 主动推送必须用【群】openConversationId。私聊/错误会话会覆盖后导致
        # groupMessages/send → robot 不存在（2026-07-16~17 事故）。
        conv_type = str(
            getattr(msg, "conversation_type", None)
            or raw.get("conversationType", "")
            or ""
        )
        is_group = conv_type == "2"
        msgtype = str(raw.get("msgtype") or getattr(msg, "msgtype", "") or "text")

        # ── 人机单聊：接收 .md 答卷文件（群聊钉钉不支持收文件）──
        if msgtype == "file" and not is_group:
            try:
                reply = await asyncio.to_thread(
                    self._handle_exam_file, raw, robot_code
                )
                if reply and sw:
                    self.reply_markdown("双周答卷", reply[:18000], msg)
                elif reply:
                    logger.info("exam file graded, no session webhook")
            except Exception as e:
                logger.error("exam file handle: %s", e)
            return AckMessage.STATUS_OK, "OK"

        logger.info(
            "handler got msg: text=%s sw=%s type=%s staff=%s robotCode=%s",
            text[:60] if text else "empty",
            "yes" if sw else "NO",
            "group" if is_group else (conv_type or "dm"),
            (sender_staff[:8] + "…") if sender_staff else "-",
            (robot_code[:20] + "…") if robot_code and len(robot_code) > 20 else (robot_code or "-"),
        )

        if not text:
            return AckMessage.STATUS_OK, "OK"

        if not sender_staff:
            if sw:
                self.reply_markdown(
                    "瑞贝卡",
                    "未能识别你的钉钉身份（staffId），暂无法记录个人学习进度。"
                    "请用钉钉私聊或群内 @ 瑞贝卡 再试。",
                    msg,
                )
            return AckMessage.STATUS_OK, "OK"

        # 报名 / 首次开通（口令或懒开户）
        try:
            from learner.roster import is_enroll_utterance, ensure_learner, resolve_learner

            if is_enroll_utterance(text):
                ensure_learner(sender_staff, nick=sender_nick, source="enroll")
                nick = sender_nick or sender_staff[:8]
                reply = f"已为你开通培养账户（{nick}）。可以说「来一题」或「出题」开始。"
                self.reply_markdown("瑞贝卡", reply, msg)
                return AckMessage.STATUS_OK, "OK"
            if resolve_learner(sender_staff) is None:
                ensure_learner(sender_staff, nick=sender_nick, source="auto")
        except Exception as e:
            logger.warning("enroll handle: %s", e)

        # 记下讨论用户（花名册 upsert）；群会话 ID 仅群聊可写
        stripped = text.strip()
        if stripped.startswith("交卷") or stripped.startswith("提交答卷"):
            try:
                from learner.biweekly_exam import submit_answer_md

                body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
                # 仅「交卷」二字 / 空正文 → 当空卷，勿把前缀当答卷内容
                if not body.strip():
                    reply = "答卷为空。请在「交卷」下一行粘贴 Markdown，或私聊发送 .md 文件。"
                    if reply and sw:
                        self.reply_markdown("双周答卷", reply, msg)
                    return AckMessage.STATUS_OK, "OK"
                if len(body) < 20 and (
                    "paper_id" not in body
                    and "作答区" not in body
                    and "第" not in body
                ):
                    body = stripped
                reply = await asyncio.to_thread(submit_answer_md, body)
                if reply:
                    self.reply_markdown("双周答卷", reply[:18000], msg)
                return AckMessage.STATUS_OK, "OK"
            except Exception as e:
                logger.error("exam text submit: %s", e)

        # 记下讨论用户（单聊推送用）；群会话 ID 仅群聊可写
        if sender_staff:
            try:
                from deliver.dingtalk_users import save_discuss_user
                save_discuss_user(
                    sender_staff,
                    nick=sender_nick,
                    source="group" if is_group else "dm",
                )
            except Exception as e:
                logger.warning("save discuss user: %s", e)

        conv_id = (
            callback.data.get("openConversationId", "")
            or callback.data.get("conversationId", "")
            or getattr(msg, "conversation_id", "")
            or ""
        )
        if conv_id and is_group:
            self._save_conversation(conv_id)
        elif conv_id and not is_group:
            logger.info(
                "skip saving conversation_id for non-group chat type=%s cid=%s…",
                conv_type or "?",
                conv_id[:16],
            )

        # 群讨论走私聊时，进度提示也尽量不刷屏群（仍可用 session 短确认）
        discuss_in_dm = False
        try:
            from config import DINGTALK_DISCUSS_IN_DM
            discuss_in_dm = bool(DINGTALK_DISCUSS_IN_DM) and is_group
        except Exception:
            discuss_in_dm = is_group

        lock = await self._lock_for(f"{conv_id or '_default'}|{sender_staff}")

        async with lock:
            def _on_progress(progress_text: str) -> None:
                if not sw:
                    return
                # 群→私聊模式：群里只回一句短状态
                tip = progress_text if not discuss_in_dm else "正在私聊里处理…"
                _send_session_webhook(sw, tip)

            def _handle_bound() -> str:
                from learner.context import bind_learner

                with bind_learner(sender_staff, binding="personal"):
                    agent = self._get_agent()
                    agent.bind_for_learner(sender_staff)
                    try:
                        return agent.handle(text, _on_progress)
                    except TypeError:
                        return agent.handle(text)

            try:
                reply = await asyncio.to_thread(_handle_bound)
                logger.info("agent reply: %s chars", len(reply) if reply else 0)
            except Exception as e:
                logger.error("agent error: %s", e)
                return AckMessage.STATUS_OK, "OK"

            if reply:
                from math_format import prepare_dingtalk_with_formulas
                body, pieces = prepare_dingtalk_with_formulas(reply)
                logger.info(
                    "agent reply text: %s chars formulas=%d (cdn-embed)",
                    len(body),
                    len(pieces),
                )
                title = (body.split("\n")[0][:30]).strip() or "瑞贝卡"
                title = title.lstrip("#* ").strip() or "瑞贝卡"
                if title.startswith("![") or title.startswith("http"):
                    title = "瑞贝卡"

                delivered_dm = False
                if discuss_in_dm and sender_staff:
                    delivered_dm = self._reply_via_oto(sender_staff, title, body)
                    if delivered_dm:
                        # 群内短确认，避免长解答刷屏
                        self.reply_markdown(
                            "瑞贝卡",
                            "已私聊回复你，请打开与「瑞贝卡」的单聊查看完整内容～",
                            msg,
                        )
                        logger.info("group→dm reply ok staff=%s…", sender_staff[:8])
                    else:
                        logger.warning("group→dm failed, fallback group reply")

                if not delivered_dm:
                    result = self.reply_markdown(title, body, msg)
                    result_str = str(result)[:300] if result else "FAILED"
                    logger.info("reply_markdown result: %s", result_str)

                tools = getattr(self._get_agent(), "last_tools_used", None) or []
                # ActionCard：私聊用 oTo 不好带 session 卡；仅同会话 webhook 跟发
                if sw and tools and not delivered_dm:
                    self._maybe_send_followup_card(sw, tools)
            else:
                logger.info("empty reply, skipped")

        return AckMessage.STATUS_OK, "OK"

    def _reply_via_oto(self, user_id: str, title: str, body: str) -> bool:
        """把完整回复发到人机单聊。"""
        try:
            from deliver.dingtalk_media import get_access_token, send_oto_markdown
            if not self._get_credentials:
                return False
            client_id, client_secret = self._get_credentials()
            if not client_id or not client_secret:
                return False
            token = get_access_token(client_id, client_secret)
            if not token:
                return False
            return send_oto_markdown(
                access_token=token,
                robot_code=client_id,
                user_id=user_id,
                title=title,
                text=body,
            )
        except Exception as e:
            logger.error("oto reply error: %s", e)
            return False

    def _maybe_send_followup_card(self, session_webhook: str, tools: list) -> None:
        """根据本轮用过的工具，跟发题目卡或周报操作卡。"""
        try:
            from deliver.dingtalk_media import send_session_action_card
            from deliver.action_cards import (
                QUESTION_ACTIONS,
                WEEKLY_ACTIONS,
                question_followup_hint,
            )
        except Exception as e:
            logger.warning("action card import: %s", e)
            return

        if "generate_question" in tools:
            ok = send_session_action_card(
                session_webhook,
                "快捷操作",
                question_followup_hint(),
                QUESTION_ACTIONS,
            )
            logger.info("followup question ActionCard: %s", ok)
        elif "build_report" in tools:
            ok = send_session_action_card(
                session_webhook,
                "周报后续",
                "根据周报选一个巩固动作：",
                WEEKLY_ACTIONS,
            )
            logger.info("followup weekly ActionCard: %s", ok)


class DingTalkBot:
    """钉钉 Bot：Stream 长连 + 群会话持久化 + 主动推送"""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._agent = None
        self.conversation_id = ""
        self._cid_file: Optional[str] = None
        self._load_cid()
        # 环境变量钉死群会话，优先于文件（防私聊串台）
        try:
            from config import DINGTALK_GROUP_CONVERSATION_ID
            pinned = (DINGTALK_GROUP_CONVERSATION_ID or "").strip()
            if pinned:
                self.conversation_id = pinned
                logger.info("使用 .env 固定群 conversation_id=%s…", pinned[:16])
        except Exception:
            pass

    def set_agent(self, agent):
        self._agent = agent

    def set_cid_file(self, path: str):
        self._cid_file = path
        self._load_cid()

    def _load_cid(self):
        if not self._cid_file:
            return
        try:
            if os.path.exists(self._cid_file):
                with open(self._cid_file) as f:
                    data = json.load(f)
                self.conversation_id = data.get("conversation_id", "")
                if self.conversation_id:
                    logger.info(
                        "恢复 conversation_id=%s… (%s)",
                        self.conversation_id[:16],
                        data.get("scope", "group"),
                    )
        except Exception as e:
            logger.warning("conversation_id 加载失败: %s", e)

    def _save_cid(self, cid: str):
        """仅应由群聊回调写入；若 .env 已固定群 ID 则不改内存推送目标。"""
        if not cid:
            return
        pinned = ""
        try:
            from config import DINGTALK_GROUP_CONVERSATION_ID
            pinned = (DINGTALK_GROUP_CONVERSATION_ID or "").strip()
        except Exception:
            pass
        if pinned:
            # 仍可把观测到的群 ID 写入文件作备份，但不覆盖推送用 pinned
            if not self._cid_file:
                return
            try:
                os.makedirs(os.path.dirname(self._cid_file), exist_ok=True)
                with open(self._cid_file, "w") as f:
                    json.dump(
                        {
                            "conversation_id": pinned,
                            "scope": "group",
                            "pinned_from_env": True,
                            "last_seen_group_cid": cid,
                        },
                        f,
                        ensure_ascii=False,
                    )
            except Exception as e:
                logger.warning("conversation_id 保存失败: %s", e)
            return
        if cid == self.conversation_id:
            return
        self.conversation_id = cid
        if not self._cid_file:
            return
        try:
            os.makedirs(os.path.dirname(self._cid_file), exist_ok=True)
            with open(self._cid_file, "w") as f:
                json.dump(
                    {
                        "conversation_id": cid,
                        "scope": "group",
                        "updated_note": "only group chat (conversationType=2)",
                    },
                    f,
                    ensure_ascii=False,
                )
            logger.info("已更新群 conversation_id=%s…", cid[:16])
        except Exception as e:
            logger.warning("conversation_id 保存失败: %s", e)

    def start(self):
        """启动 Stream 客户端（阻塞，应在主线程调用）。"""
        credential = dingtalk_stream.Credential(self.client_id, self.client_secret)
        self._client = dingtalk_stream.DingTalkStreamClient(credential)

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("114.114.114.114", 80))
            local_ip = s.getsockname()[0]
            s.close()
            self._client.get_host_ip = lambda: local_ip
        except Exception:
            pass

        handler = DingTalkHandler(
            agent_getter=lambda: self._agent,
            conversation_saver=self._save_cid,
            credentials_getter=lambda: (self.client_id, self.client_secret),
        )
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
            handler,
        )

        logger.info("钉钉 Stream 客户端启动（主线程）")
        self._client.start_forever()

    def stop(self):
        if self._client and self._client.websocket:
            try:
                import asyncio
                if hasattr(self._client.websocket.close, "__await__"):
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self._client.websocket.close())
                    loop.close()
                else:
                    self._client.websocket.close()
            except Exception:
                pass

    def send_push(self, content: str) -> bool:
        if not self.conversation_id:
            logger.warning("send_push skipped: conversation_id 为空（用户未发过消息）")
            return False
        try:
            from math_format import prepare_dingtalk_with_formulas
            # 群推送附简短导流：讨论走私聊
            tip = (
                "\n\n---\n"
                "答疑/交作业请**私聊瑞贝卡**（点机器人头像进单聊），群里只做推送通知。"
            )
            if "私聊瑞贝卡" not in (content or ""):
                content = (content or "").rstrip() + tip
            body, pieces = prepare_dingtalk_with_formulas(content)
            ok = self._push_via_api(body)
            if pieces:
                n = self._push_formula_images(pieces)
                logger.info("push formula images: %d/%d", n, len(pieces))
            return ok
        except Exception as e:
            logger.error("send_push 失败: %s", e)
            return False

    def send_question_action_card(self, subject: str = "") -> bool:
        """主动推送：出题后的快捷按钮卡。"""
        if not self.conversation_id:
            return False
        from deliver.action_cards import QUESTION_ACTIONS, question_card_text
        from deliver.dingtalk_media import get_access_token, send_group_action_card

        try:
            token = get_access_token(self.client_id, self.client_secret)
            ok = send_group_action_card(
                access_token=token,
                robot_code=self.client_id,
                open_conversation_id=self.conversation_id,
                title="快捷操作",
                text=question_card_text(subject),
                buttons=QUESTION_ACTIONS,
            )
            logger.info("question ActionCard push: %s subject=%s", ok, subject)
            return ok
        except Exception as e:
            logger.error("question ActionCard failed: %s", e)
            return False

    def send_weekly_action_card(self, report_text: str) -> bool:
        """主动推送：学习周报 ActionCard（正文=周报，按钮=巩固动作）。"""
        if not self.conversation_id:
            return False
        from deliver.action_cards import WEEKLY_ACTIONS, weekly_card_title
        from deliver.dingtalk_media import get_access_token, send_group_action_card

        # ActionCard text 建议控制长度；过长截断并提示完整版可说「周报」
        text = (report_text or "").strip()
        if len(text) > 1800:
            text = text[:1800].rstrip() + "\n\n…（完整版回复「周报」）"
        try:
            token = get_access_token(self.client_id, self.client_secret)
            ok = send_group_action_card(
                access_token=token,
                robot_code=self.client_id,
                open_conversation_id=self.conversation_id,
                title=weekly_card_title(),
                text=text or "本周数据较少，多练几题后再看周报。",
                buttons=WEEKLY_ACTIONS,
            )
            logger.info("weekly ActionCard push: %s", ok)
            return ok
        except Exception as e:
            logger.error("weekly ActionCard failed: %s", e)
            return False

    def _push_formula_images(self, pieces: list) -> int:
        try:
            from deliver.latex_render import render_pieces
            from deliver.dingtalk_media import (
                get_access_token,
                upload_image,
                send_group_image,
            )
        except Exception as e:
            logger.warning("push formula deps: %s", e)
            return 0
        rendered = render_pieces(pieces[:MAX_FORMULA_IMAGES])
        if not rendered:
            return 0
        try:
            token = get_access_token(self.client_id, self.client_secret)
        except Exception as e:
            logger.warning("push formula token: %s", e)
            return 0
        ok_n = 0
        for piece, png in rendered:
            mid = upload_image(token, png, filename=f"{piece.placeholder}.png")
            if mid and send_group_image(
                access_token=token,
                robot_code=self.client_id,
                open_conversation_id=self.conversation_id,
                media_id=mid,
            ):
                ok_n += 1
        return ok_n

    def send_file(self, file_bytes: bytes, file_name: str, file_type: str) -> bool:
        """扩展：群内发文件（sampleFile）。"""
        if not self.conversation_id:
            return False
        from deliver.dingtalk_media import (
            get_access_token,
            upload_file,
            send_group_file,
        )
        token = get_access_token(self.client_id, self.client_secret)
        mid = upload_file(token, file_bytes, file_name, file_type="file")
        if not mid:
            return False
        return send_group_file(
            access_token=token,
            robot_code=self.client_id,
            open_conversation_id=self.conversation_id,
            media_id=mid,
            file_name=file_name,
            file_type=file_type,
        )

    def send_biweekly_papers(self, papers: list) -> bool:
        """推送双周试卷：markdown 摘要 + .md 文件附件。"""
        ok_any = False
        for paper in papers or []:
            pid = paper.get("paper_id") or ""
            title = paper.get("title") or pid
            n = paper.get("n_ok") or 0
            md = paper.get("public_md") or ""
            summary = (
                f"### 双周检测卷 · {title}\n\n"
                f"- 试卷 ID：`{pid}`\n"
                f"- 题数：{n}\n"
                f"- 请下载附件作答；**人机单聊**发回 `.md` 答卷"
                f"（或发「交卷」+ 正文）。群聊无法收文件。\n"
            )
            if self.send_push(summary):
                ok_any = True
            if md:
                try:
                    raw = md.encode("utf-8")
                    if self.send_file(raw, f"{pid}.md", "md"):
                        ok_any = True
                    else:
                        self.send_push(md[:15000])
                except Exception as e:
                    logger.warning("biweekly file push: %s", e)
        return ok_any

    def _push_via_api(self, content: str) -> bool:
        r = requests.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": self.client_id, "appSecret": self.client_secret},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json().get("accessToken", "")
        if not token:
            logger.error("获取 accessToken 失败")
            return False

        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": token,
        }
        body = {
            "robotCode": self.client_id,
            "openConversationId": self.conversation_id,
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({"title": "教学推送", "text": content}),
        }
        resp = requests.post(
            "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
            headers=headers,
            json=body,
            timeout=10,
        )
        if resp.ok:
            return True
        logger.error("push API 错误: %s %s", resp.status_code, resp.text[:200])
        return False


class DingTalkPushBridge:
    """推送桥 — 对接 DingTalkBot.send_push，给 scheduler 用"""

    def __init__(self, bot: DingTalkBot):
        self.bot = bot

    def send(self, content: str) -> bool:
        return self.bot.send_push(content)

    def is_ready(self) -> bool:
        return bool(self.bot.conversation_id)
