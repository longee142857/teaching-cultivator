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


def _resolve_blocks_path(staff_id: str | None, base_dir: str | None) -> str:
    if base_dir:
        return os.path.join(base_dir, "memory_blocks.json")
    if staff_id:
        from learner import paths as P
        return P.memory_blocks_path(staff_id)
    try:
        from learner import paths as P
        return P.memory_blocks_path()
    except Exception:
        return BLOCKS_PATH


def _resolve_last_push_path(staff_id: str | None, base_dir: str | None) -> str:
    if base_dir:
        personal = os.path.join(base_dir, "last_push.json")
        if os.path.isfile(personal):
            return personal
        try:
            from learner import paths as P
            pub = P.public_last_class_path()
            if os.path.isfile(pub):
                return pub
        except Exception:
            pass
        return personal
    try:
        from learner import paths as P
        if staff_id:
            personal = P.last_push_path(staff_id)
            if os.path.isfile(personal):
                return personal
            pub = P.public_last_class_path()
            if os.path.isfile(pub):
                return pub
            return personal
        for path in (P.last_push_path(), P.public_last_class_path()):
            if os.path.isfile(path):
                return path
        return P.last_push_path()
    except Exception:
        return LAST_PUSH_PATH

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
    """读写 memory_blocks.json（默认当前学员目录）。"""

    def __init__(self, staff_id: str | None = None, base_dir: str | None = None) -> None:
        self._staff_id = staff_id
        self._base_dir = base_dir
        self._data = _default_blocks()
        self.load()

    @property
    def _blocks_path(self) -> str:
        return _resolve_blocks_path(self._staff_id, self._base_dir)

    @property
    def _last_push_path(self) -> str:
        return _resolve_last_push_path(self._staff_id, self._base_dir)

    def load(self) -> None:
        path = self._blocks_path
        try:
            if not os.path.isfile(path):
                return
            with open(path, encoding="utf-8") as f:
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
            path = self._blocks_path
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._data["session"]["updated_at"] = time.time()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
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
        try:
            from learner.roster import allows_learning_writes

            if not allows_learning_writes(self._staff_id):
                return
        except Exception:
            pass
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
        """从 last_push / last_class 同步 active_question。"""
        try:
            from learner.roster import allows_learning_writes

            if not allows_learning_writes(self._staff_id):
                return
        except Exception:
            pass
        try:
            lp = self._last_push_path
            if not os.path.isfile(lp):
                from learner import paths as P
                pub = P.public_last_class_path()
                if os.path.isfile(pub):
                    lp = pub
                else:
                    return
            with open(lp, encoding="utf-8") as f:
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
        """定时/主动出题后：更新当前题与 phase，todos 改为等待作答。

        subject/kp 为空时从文件补读（个人 last_push 或公共 last_class），
        保证 active_question 与最新推送对齐，防错题叙事粘滞。
        """
        try:
            from learner.roster import allows_learning_writes

            if not allows_learning_writes(self._staff_id):
                return
        except Exception:
            pass
        if not subject or not kp:
            try:
                # 优先公共 last_class（定时推送写这里），其次个人 last_push
                from learner import paths as P
                candidates = [self._last_push_path]
                pub = P.public_last_class_path()
                if os.path.isfile(pub):
                    candidates.insert(0, pub)
                for lp in candidates:
                    if os.path.isfile(lp):
                        with open(lp, encoding="utf-8") as f:
                            data = json.load(f)
                        if not subject:
                            subject = str(data.get("subject") or "")
                        if not kp:
                            kp = str(data.get("kp") or "")
                        if subject and kp:
                            break
            except Exception:
                pass
        self.set_active_question(
            content,
            source="public_class" if "public" in (self._last_push_path.replace("\\", "/")) else "last_push",
            subject=subject,
            kp=kp,
        )
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
            # 批改后同步 active_question 到最新 last_push/last_class（防串题）
            self.refresh_from_last_push()
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
