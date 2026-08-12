"""DingTalk → 本机 Pi RPC 桥（feature flag PI_RPC_ENABLED）。

连接方式（二选一）：
1. PI_RPC_CMD — 本进程拉起 `pi --mode rpc …`（stdin/stdout JSONL）
2. 否则 TCP — PI_RPC_HOST:PI_RPC_PORT（由主机 systemd/socat 接到 Pi）

会话约定：
  PI_SESSION_DIR/learners/{safe_id}.jsonl
  指针：data/learners/{safe_id}/pi_session.json
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TextIO

from learner.paths import ensure_learner_dir, safe_learner_id

logger = logging.getLogger(__name__)

# 工具名 → 中文进度提示（与旧 Agent 的 _TOOL_PROGRESS 对齐）
TOOL_PROGRESS: dict[str, str] = {
    "list_recent_entries": "正在查题库索引…",
    "find_record_entry": "正在提取题目全文…",
    "list_today_questions": "正在读取今日题库…",
    "grade_answer": "正在批改…",
    "generate_question": "正在出题…",
    "show_solution": "正在生成解答…",
    "build_report": "正在生成报告…",
    "get_learner_snapshot": "正在读取学习指标…",
    "note_weak_point": "正在记录薄弱点…",
    "adjust_difficulty": "正在调整难度…",
    "get_active_question": "正在读取当前题目…",
    "list_knowledge_points": "正在读取考纲知识点…",
    "kb_query": "正在查询知识库…",
    "kb_enqueue": "正在登记教材回填…",
    "list_exam_bank": "正在检索试卷库…",
    "get_exam_paper": "正在读取试卷…",
    "get_exam_result": "正在读取批改结果…",
    "submit_exam_answer_md": "正在批改双周卷…",
    "propose_add_kp": "正在登记知识点提案…",
    "confirm_add_kp": "正在写入知识点…",
    "cancel_add_kp": "正在取消…",
    "propose_override_grade": "正在登记纠正提案…",
    "confirm_override": "正在重算掌握度…",
    "cancel_override": "正在取消纠正…",
    "write_feedback": "正在写入反馈…",
    "ocr_handwriting": "正在识别手写图…",
    "grade_handwriting": "正在识别并批改手写作答…",
}

PI_RPC_ENABLED = os.environ.get("PI_RPC_ENABLED", "0") == "1"
PI_RPC_HOST = os.environ.get("PI_RPC_HOST", "127.0.0.1")
PI_RPC_PORT = int(os.environ.get("PI_RPC_PORT", "8780"))
PI_SESSION_DIR = os.environ.get("PI_SESSION_DIR", "/home/ubuntu/pi-sessions")
PI_RPC_CMD = os.environ.get("PI_RPC_CMD", "")
PI_RPC_TIMEOUT = float(os.environ.get("PI_RPC_TIMEOUT", "180"))
PI_WORKSPACE = os.environ.get("PI_WORKSPACE", "/home/ubuntu/pi-workspace")


def enabled() -> bool:
    return PI_RPC_ENABLED


def session_path_for(staff_id: str) -> str:
    sid = safe_learner_id(staff_id)
    return str(Path(PI_SESSION_DIR) / "learners" / f"{sid}.jsonl")


def write_session_pointer(staff_id: str, session_path: str) -> None:
    d = ensure_learner_dir(staff_id)
    ptr = Path(d) / "pi_session.json"
    ptr.write_text(
        json.dumps(
            {
                "session_path": session_path,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def bind_active_learner(staff_id: str) -> Path:
    """写入当前 ask 绑定的学员，供 Pi extension 作为 X-Learner-Id。

    桥的 ask() 已全局加锁，文件在整轮工具调用期间有效。
    """
    from config import DATA_DIR

    sid = (staff_id or "").strip()
    if not sid:
        raise ValueError("empty staff_id")
    path = Path(DATA_DIR) / "pi_active_learner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "learner_id": sid,
                "safe_id": safe_learner_id(sid),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def seed_session_file(path: str) -> None:
    """写入 Pi 可 switch 的空会话（仅 header）。

    Pi RPC 的 `new_session` 会推迟到首条消息才落盘，此前 get_state.sessionFile
    指向尚不存在的路径；直接 seed + switch 更稳。
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    header = {
        "type": "session",
        "version": 3,
        "id": str(uuid.uuid4()),
        "timestamp": ts,
        "cwd": PI_WORKSPACE,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")


class _JsonlIO:
    """统一 stdin/stdout 或 socket 的 JSONL。"""

    def __init__(self, reader: TextIO, writer: TextIO, *, sock: socket.socket | None = None):
        self._r = reader
        self._w = writer
        self._sock = sock
        self._buf = ""
        self._req = 0
        self._lock = threading.Lock()
        self._pending_events: list[dict] = []

    def close(self) -> None:
        try:
            self._w.close()
        except Exception:
            pass
        try:
            self._r.close()
        except Exception:
            pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _readline(self, deadline: float) -> str:
        while True:
            if "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                return line.rstrip("\r")
            if time.time() > deadline:
                raise TimeoutError("pi rpc readline timeout")
            # nonblocking-ish read
            if self._sock:
                self._sock.settimeout(max(0.05, min(1.0, deadline - time.time())))
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise ConnectionError("pi rpc connection closed")
                self._buf += chunk.decode("utf-8", errors="replace")
            else:
                # pipe: use short select via timeout on buffered read — blocking with poll
                import select

                ready, _, _ = select.select([self._r], [], [], 0.2)
                if not ready:
                    continue
                chunk = self._r.read(1)
                if chunk == "":
                    raise ConnectionError("pi rpc pipe closed")
                # read available
                self._buf += chunk
                while True:
                    ready, _, _ = select.select([self._r], [], [], 0)
                    if not ready:
                        break
                    c = self._r.read(4096)
                    if not c:
                        break
                    self._buf += c

    def request(self, obj: dict, *, timeout: float | None = None) -> dict:
        with self._lock:
            self._req += 1
            rid = obj.get("id") or f"req-{self._req}"
            payload = {**obj, "id": rid}
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            self._w.write(line)
            self._w.flush()
            deadline = time.time() + (timeout if timeout is not None else PI_RPC_TIMEOUT)
            while True:
                raw = self._readline(deadline)
                if not raw.strip():
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "response" and msg.get("id") == rid:
                    return msg
                # 非 response 事件：缓存供 drain_events 读取（避免被 request 阻塞读丢弃）
                if msg.get("type") != "response":
                    if not hasattr(self, "_pending_events"):
                        self._pending_events = []
                    self._pending_events.append(msg)

    def drain_events(self, deadline: float) -> list[dict]:
        """非阻塞尽量排空事件（含 request() 期间缓存的）。"""
        events: list[dict] = []
        with self._lock:
            # 先取出 request() 期间缓存的事件
            if self._pending_events:
                events.extend(self._pending_events)
                self._pending_events = []
            while time.time() < deadline:
                if "\n" not in self._buf:
                    if self._sock:
                        self._sock.settimeout(0.05)
                        try:
                            chunk = self._sock.recv(65536)
                        except socket.timeout:
                            break
                        if not chunk:
                            break
                        self._buf += chunk.decode("utf-8", errors="replace")
                    else:
                        import select

                        ready, _, _ = select.select([self._r], [], [], 0.05)
                        if not ready:
                            break
                        c = self._r.read(4096)
                        if not c:
                            break
                        self._buf += c
                    continue
                line, self._buf = self._buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "response":
                    # 塞回缓冲：极少见；忽略孤儿 response
                    continue
                events.append(msg)
        return events


class PiRpcBridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._io: Optional[_JsonlIO] = None
        self._proc: Optional[subprocess.Popen] = None
        self._bound_session: str = ""

    def _close_io(self) -> None:
        if self._io:
            try:
                self._io.close()
            except Exception:
                pass
        self._io = None
        self._proc = None
        self._bound_session = ""

    def _connect(self) -> _JsonlIO:
        if self._io:
            return self._io
        # 新连接：不信任旧绑定（Pi 进程可能已换会话）
        self._bound_session = ""
        if PI_RPC_CMD:
            args = shlex.split(PI_RPC_CMD)
            Path(PI_WORKSPACE).mkdir(parents=True, exist_ok=True)
            Path(PI_SESSION_DIR).mkdir(parents=True, exist_ok=True)
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=PI_WORKSPACE,
                env={**os.environ, "AI_AGENT": "pi", "PI_CODING_AGENT": "true"},
            )
            assert self._proc.stdin and self._proc.stdout
            self._io = _JsonlIO(self._proc.stdout, self._proc.stdin)
            return self._io
        sock = socket.create_connection((PI_RPC_HOST, PI_RPC_PORT), timeout=10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # makefile for write; read via sock in _JsonlIO
        w = sock.makefile("w", encoding="utf-8", newline="\n")
        r = sock.makefile("r", encoding="utf-8", newline="\n")
        self._io = _JsonlIO(r, w, sock=sock)
        return self._io

    def _get_session_file(self, io: _JsonlIO) -> str:
        st = io.request({"type": "get_state"}, timeout=15)
        return str((st.get("data") or {}).get("sessionFile") or "")

    def _ensure_session(self, staff_id: str) -> str:
        """保证 Pi 活动会话 = 学员 canonical 路径（一人一文件，可持久）。

        旧 bug：`new_session` 只在 session-dir 下生成 UUID 文件，却把指针写成
        learners/{id}.jsonl（文件从未创建）→ 每次桥重置再 new_session → 多文件、
        cow 自称「只有一轮记忆」。
        """
        path = session_path_for(staff_id)
        canon = Path(path)
        canon.parent.mkdir(parents=True, exist_ok=True)
        io = self._connect()

        try:
            current = self._get_session_file(io)
        except Exception:
            current = ""

        # 已有 canonical：必要时 switch 上去
        if canon.is_file() and canon.stat().st_size > 0:
            if current != path:
                resp = io.request({"type": "switch_session", "sessionPath": path})
                if resp.get("success") is False:
                    raise RuntimeError(f"switch_session failed: {resp}")
                logger.info("pi session switched → %s", path)
            self._bound_session = path
            write_session_pointer(staff_id, path)
            return path

        # canonical 不存在/空：seed 合法空会话再 switch（勿依赖 new_session 落盘）
        seed_session_file(path)
        resp = io.request({"type": "switch_session", "sessionPath": path})
        if resp.get("success") is False:
            raise RuntimeError(f"switch_session(new) failed: {resp}")
        try:
            io.request(
                {
                    "type": "set_session_name",
                    "name": f"learner-{safe_learner_id(staff_id)}",
                }
            )
        except Exception:
            pass
        self._bound_session = path
        write_session_pointer(staff_id, path)
        logger.info("pi session seeded+switched → %s", path)
        return path

    def ask(
        self,
        staff_id: str,
        text: str,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        with self._lock:
            try:
                return self._ask_once(staff_id, text, on_progress)
            except (BrokenPipeError, ConnectionError, TimeoutError, OSError) as e:
                # pi-rpc 单独重启后旧 TCP 会 Broken pipe；清连接再试一次
                logger.warning("pi rpc stale connection (%s); reconnecting", e)
                self._close_io()
                return self._ask_once(staff_id, text, on_progress)

    def _ask_once(
        self,
        staff_id: str,
        text: str,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        bind_active_learner(staff_id)
        self._ensure_session(staff_id)
        io = self._connect()
        msg = (
            f"[learner={staff_id}] 若涉及当前推送题，先调用 get_active_question。"
            " 本会话上下文含历史轮次；钉钉表情可能显示为 [名称]。"
            " 勿用 bash 扫描 pi-sessions 旧文件来回答「刚才说了什么」。"
            " 私聊图片仅暂存：用户明确作答/交卷时才调 grade_handwriting；"
            "只想看图内容用 ocr_handwriting；无关截图勿批改。\n\n"
            + (text or "")
        )
        resp = io.request({"type": "prompt", "message": msg}, timeout=15)
        if not resp.get("success"):
            resp = io.request(
                {
                    "type": "prompt",
                    "message": msg,
                    "streamingBehavior": "followUp",
                },
                timeout=15,
            )
        if not resp.get("success"):
            raise RuntimeError(f"pi prompt failed: {resp}")

        deadline = time.time() + PI_RPC_TIMEOUT
        last_text = ""
        settled = False
        idle_rounds = 0
        _sent_tools: set[str] = set()  # 每个工具每次对话只发一句提示

        def _send_tool_progress(tname: str) -> None:
            if not on_progress or not tname:
                return
            if tname in _sent_tools:
                return
            _sent_tools.add(tname)
            tip = TOOL_PROGRESS.get(tname, f"正在调用 {tname}…")
            try:
                on_progress(tip)
            except Exception:
                pass

        _stable_rounds = 0
        _prev_text = ""
        while time.time() < deadline:
            events = io.drain_events(time.time() + 0.35)
            for ev in events:
                etype = ev.get("type")
                # agent_settled = Pi 完成一轮 agent（含工具循环），快速路径
                if etype == "agent_settled":
                    settled = True
                if etype == "tool_execution_start":
                    # 工具调用：每个工具每次对话只发一句提示（不重复、不刷屏）
                    tname = str(ev.get("toolName") or "")
                    _send_tool_progress(tname)
            try:
                st = io.request({"type": "get_state"}, timeout=10)
                _sdata = st.get("data") or {}
                _streaming = bool(
                    _sdata.get("isStreaming")
                    or _sdata.get("streaming")
                    or _sdata.get("isRunning")
                )
            except Exception:
                _streaming = True
            try:
                ta = io.request({"type": "get_last_assistant_text"}, timeout=10)
                tdata = ta.get("data") or {}
                text_out = (
                    tdata.get("text")
                    or tdata.get("lastAssistantText")
                    or ""
                )
                if text_out:
                    last_text = text_out
            except Exception:
                pass

            if settled:
                # agent_settled：取最终回复即完成
                if last_text:
                    break
                idle_rounds += 1
                if idle_rounds >= 2:
                    break
            elif not _streaming and last_text:
                # 文本稳定（连续 3 次相同 + 非 streaming）= Pi 完成
                if last_text == _prev_text:
                    _stable_rounds += 1
                    if _stable_rounds >= 3:
                        break
                else:
                    _stable_rounds = 0
                _prev_text = last_text
            else:
                _stable_rounds = 0
                _prev_text = ""
            time.sleep(0.35)
        return last_text or "（Pi 无文本回复）"

    def notify_new_push(self, staff_id: str, *, subject: str = "", kp: str = "") -> None:
        if not enabled():
            return
        marker = (
            f"[NEW_PUSH subject={subject} kp={kp} "
            f"ts={datetime.now(timezone.utc).isoformat()}]"
        )
        with self._lock:
            self._ensure_session(staff_id)
            io = self._connect()
            io.request(
                {
                    "type": "prompt",
                    "message": marker + "\n新一轮推送已开始，后续问答挂在此分支。",
                }
            )
            time.sleep(0.6)
            try:
                fm = io.request({"type": "get_fork_messages"}, timeout=15)
            except Exception:
                return
            msgs = (fm.get("data") or {}).get("messages") or []
            entry_id = None
            for m in reversed(msgs):
                eid = m.get("id") or m.get("entryId")
                content = str(m.get("text") or m.get("content") or "")
                if eid and "NEW_PUSH" in content:
                    entry_id = eid
                    break
            if entry_id:
                try:
                    io.request({"type": "fork", "entryId": entry_id}, timeout=15)
                except Exception:
                    pass


_BRIDGE: Optional[PiRpcBridge] = None
_BRIDGE_LOCK = threading.Lock()


def get_bridge() -> PiRpcBridge:
    global _BRIDGE
    with _BRIDGE_LOCK:
        if _BRIDGE is None:
            _BRIDGE = PiRpcBridge()
        return _BRIDGE
