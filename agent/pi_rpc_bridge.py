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
import os
import shlex
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TextIO

from learner.paths import ensure_learner_dir, safe_learner_id

# 工具名 → 中文进度提示（与旧 Agent 的 _TOOL_PROGRESS 对齐）
TOOL_PROGRESS: dict[str, str] = {
    "list_recent_entries": "正在查题库索引…",
    "find_record_entry": "正在提取题目全文…",
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

    def _connect(self) -> _JsonlIO:
        if self._io:
            return self._io
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

    def _ensure_session(self, staff_id: str) -> str:
        path = session_path_for(staff_id)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        io = self._connect()
        if self._bound_session != path:
            if Path(path).is_file() and Path(path).stat().st_size > 0:
                resp = io.request({"type": "switch_session", "sessionPath": path})
            else:
                resp = io.request({"type": "new_session"})
                try:
                    io.request(
                        {
                            "type": "set_session_name",
                            "name": f"learner-{safe_learner_id(staff_id)}",
                        }
                    )
                except Exception:
                    pass
            if resp.get("success") is False:
                raise RuntimeError(f"session switch failed: {resp}")
            self._bound_session = path
            write_session_pointer(staff_id, path)
        return path

    def ask(
        self,
        staff_id: str,
        text: str,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        with self._lock:
            self._ensure_session(staff_id)
            io = self._connect()
            msg = (
                f"[learner={staff_id}] 若涉及当前推送题，先调用 get_active_question。\n\n"
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
            _progress_calls = 0
            _last_progress_at = 0.0

            def _limited_progress(txt: str) -> None:
                # 限频：工具提示（正在X…）最多 10 次 + 间隔 1.5s；泛化提示最多 3 次
                nonlocal _progress_calls, _last_progress_at
                if not on_progress:
                    return
                now = time.time()
                is_tool = not txt.startswith("Cow ")
                if _progress_calls >= 10:
                    return
                if (now - _last_progress_at) < 1.5:
                    return
                if not is_tool and _progress_calls >= 3:
                    return
                _progress_calls += 1
                _last_progress_at = now
                try:
                    on_progress(txt)
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
                        # 工具调用：显示「正在X…」而非泛化「处理中」
                        tname = str(ev.get("toolName") or "")
                        tip = TOOL_PROGRESS.get(tname, f"正在调用 {tname}…")
                        _limited_progress(tip)
                    elif etype in ("message_update", "turn_start"):
                        _limited_progress("Cow 处理中…")
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
