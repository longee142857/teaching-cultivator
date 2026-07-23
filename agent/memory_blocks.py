"""Letta-lite core memory blocks — 常驻 system 的会话状态。

blocks:
  session          — phase + working_todos
  active_question  — 当前题引用（全文权威在 last_push.json）
  learner_digest   — 压缩版学习者快照
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from config import DATA_DIR

BLOCKS_PATH = os.path.join(DATA_DIR, "memory_blocks.json")
LAST_PUSH_PATH = os.path.join(DATA_DIR, "last_push.json")

PHASE_IDLE = "idle"
PHASE_AWAITING = "awaiting_answer"
PHASE_REVIEWING = "reviewing"
PHASE_RETRIEVING = "retrieving"

MAX_TODOS = 5
QUESTION_PREVIEW_LEN = 200


def _default_blocks() -> dict[str, Any]:
    return {
        "session": {
            "phase": PHASE_IDLE,
            "updated_at": 0.0,
            "working_todos": [],
        },
        "active_question": {
            "source": "",
            "preview": "",
            "subject": "",
            "kp": "",
            "char_len": 0,
        },
        "learner_digest": "",
    }


class MemoryBlocks:
    """读写 data/memory_blocks.json。"""

    def __init__(self) -> None:
        self._data = _default_blocks()
        self.load()

    def load(self) -> None:
        try:
            if not os.path.isfile(BLOCKS_PATH):
                return
            with open(BLOCKS_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return
            base = _default_blocks()
            for key in base:
                if isinstance(raw.get(key), dict) and key != "learner_digest":
                    base[key].update(raw[key])
                elif key == "learner_digest" and isinstance(raw.get(key), str):
                    base[key] = raw[key]
            # working_todos 完整替换
            sess = raw.get("session")
            if isinstance(sess, dict) and isinstance(sess.get("working_todos"), list):
                base["session"]["working_todos"] = sess["working_todos"][:MAX_TODOS]
            self._data = base
        except Exception:
            self._data = _default_blocks()

    def save(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            self._data["session"]["updated_at"] = time.time()
            tmp = BLOCKS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, BLOCKS_PATH)
        except Exception:
            pass

    @property
    def phase(self) -> str:
        return str(self._data["session"].get("phase") or PHASE_IDLE)

    @property
    def todos(self) -> list[dict]:
        return list(self._data["session"].get("working_todos") or [])

    def set_phase(self, phase: str) -> None:
        self._data["session"]["phase"] = phase
        self._data["session"]["updated_at"] = time.time()

    def set_todos(self, todos: list[dict]) -> None:
        cleaned = []
        for t in todos[:MAX_TODOS]:
            if not isinstance(t, dict):
                continue
            cleaned.append({
                "id": str(t.get("id") or f"t{len(cleaned)+1}"),
                "content": str(t.get("content") or "")[:120],
                "status": str(t.get("status") or "pending"),
            })
        self._data["session"]["working_todos"] = cleaned

    def clear_todos(self) -> None:
        self._data["session"]["working_todos"] = []

    def set_active_question(
        self,
        content: str,
        *,
        source: str = "last_push",
        subject: str = "",
        kp: str = "",
    ) -> None:
        preview = (content or "").replace("\n", " ").strip()
        if len(preview) > QUESTION_PREVIEW_LEN:
            preview = preview[:QUESTION_PREVIEW_LEN] + "…"
        self._data["active_question"] = {
            "source": source,
            "preview": preview,
            "subject": subject or "",
            "kp": kp or "",
            "char_len": len(content or ""),
        }

    def refresh_from_last_push(self) -> None:
        """从 last_push.json 同步 active_question。"""
        try:
            if not os.path.isfile(LAST_PUSH_PATH):
                return
            with open(LAST_PUSH_PATH, encoding="utf-8") as f:
                data = json.load(f)
            q = data.get("question") or ""
            if q:
                self.set_active_question(
                    q,
                    source="last_push",
                    subject=str(data.get("subject") or ""),
                    kp=str(data.get("kp") or ""),
                )
        except Exception:
            pass

    def refresh_learner_digest(self) -> None:
        """压缩学习者快照进 block（失败则留空）。"""
        try:
            from learner.snapshot import build_learner_snapshot
            full = build_learner_snapshot(days=7)
            # 控制长度：保留要点行
            lines = [ln for ln in full.splitlines() if ln.strip()]
            digest_lines = []
            for ln in lines:
                if ln.startswith("##"):
                    digest_lines.append("## 学习者摘要")
                    continue
                digest_lines.append(ln)
                if len("\n".join(digest_lines)) > 1200:
                    break
            self._data["learner_digest"] = "\n".join(digest_lines)
        except Exception:
            self._data["learner_digest"] = ""

    def on_new_push(self, content: str, *, subject: str = "", kp: str = "") -> None:
        """定时/主动出题后：更新当前题与 phase，todos 改为等待作答。"""
        if not subject:
            try:
                if os.path.isfile(LAST_PUSH_PATH):
                    with open(LAST_PUSH_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                    subject = str(data.get("subject") or "")
                    kp = kp or str(data.get("kp") or "")
            except Exception:
                pass
        self.set_active_question(content, source="last_push", subject=subject, kp=kp)
        self.set_phase(PHASE_AWAITING)
        self.set_todos([
            {"id": "await_answer", "content": "等待用户作答当前题", "status": "pending"},
        ])
        self.refresh_learner_digest()
        self.save()

    def apply_tool_effects(self, tool_name: str) -> None:
        """Harness 根据工具结果自动推进 phase / todos。"""
        todos = self.todos
        if tool_name == "list_recent_entries":
            self.set_phase(PHASE_RETRIEVING)
            # 完成「列索引」，确保有「取全文」待办
            todos = [t for t in todos if t.get("id") != "list_index"]
            todos.append({
                "id": "fetch_full",
                "content": "用 find_record_entry 取题目全文",
                "status": "pending",
            })
            self.set_todos(todos)
        elif tool_name == "find_record_entry":
            self.set_phase(PHASE_RETRIEVING)
            todos = [
                {**t, "status": "completed"} if t.get("id") == "fetch_full" else t
                for t in todos
            ]
            self.set_todos(todos)
        elif tool_name == "generate_question":
            self.set_phase(PHASE_AWAITING)
            self.set_todos([
                {"id": "await_answer", "content": "等待用户作答当前题", "status": "pending"},
            ])
            self.refresh_from_last_push()
        elif tool_name == "grade_answer":
            self.set_phase(PHASE_REVIEWING)
            self.set_todos([
                {"id": "review_done", "content": "批改已完成，可讲解或出下一题", "status": "completed"},
            ])
            self.refresh_learner_digest()
        elif tool_name == "show_solution":
            self.set_phase(PHASE_REVIEWING)
        elif tool_name in ("note_weak_point", "adjust_difficulty", "get_learner_snapshot"):
            self.refresh_learner_digest()

    def format_blocks_for_system(self) -> str:
        """拼进 system prompt 的 core blocks 文本。"""
        sess = self._data["session"]
        aq = self._data["active_question"]
        parts = ["## Core Memory Blocks"]

        parts.append(f"- phase: {sess.get('phase', PHASE_IDLE)}")
        todos = sess.get("working_todos") or []
        if todos:
            todo_lines = []
            for t in todos:
                st = t.get("status", "pending")
                todo_lines.append(f"  - [{st}] {t.get('id')}: {t.get('content')}")
            parts.append("- working_todos:\n" + "\n".join(todo_lines))
        else:
            parts.append("- working_todos: （无）")

        if aq.get("preview") or aq.get("char_len"):
            subj = aq.get("subject") or "?"
            kp = aq.get("kp") or ""
            kp_s = f"/{kp}" if kp else ""
            parts.append(
                f"- active_question: source={aq.get('source') or '?'} "
                f"{subj}{kp_s} 全文{aq.get('char_len', 0)}字\n"
                f"  预览：{aq.get('preview') or '（空）'}\n"
                "  批改最近推送时 grade_answer 的 last_question 请传空字符串。"
            )
        else:
            parts.append("- active_question: （无）")

        digest = self._data.get("learner_digest") or ""
        if digest:
            parts.append(digest)

        return "\n".join(parts)

    def format_reminder(self, *, last_tools: list[str] | None = None, step: int = 0) -> str:
        """每步注入的轻量 system reminder。"""
        lines = ["【System Reminder】"]
        lines.append(f"step={step} phase={self.phase}")
        open_todos = [t for t in self.todos if t.get("status") != "completed"]
        if open_todos:
            lines.append(
                "开放 todos："
                + "; ".join(f"{t.get('id')}={t.get('content')}" for t in open_todos)
            )
        else:
            lines.append("开放 todos：无")
        if last_tools:
            lines.append("本步刚执行工具：" + ", ".join(last_tools))
            lines.append(
                "工具已执行完毕。若仍缺信息可继续调工具；"
                "否则必须用自然语言交付完整结果，禁止只承诺「我来查/提取」。"
            )
        return "\n".join(lines)
