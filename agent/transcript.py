"""结构化对话 transcript — 保留 tool_calls / tool 消息 + Condenser。

替代扁平 agent_memory.json（启动时自动迁移）。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from config import DATA_DIR

TRANSCRIPT_PATH = os.path.join(DATA_DIR, "agent_transcript.json")
LEGACY_MEMORY_PATH = os.path.join(DATA_DIR, "agent_memory.json")

TRANSCRIPT_MAX_MSGS = 40
TOOL_CONTENT_MAX = 4000
TRANSCRIPT_TTL_SEC = 24 * 3600


def _truncate_tool_content(content: str) -> str:
    if not isinstance(content, str):
        return str(content)
    if len(content) <= TOOL_CONTENT_MAX:
        return content
    return content[:TOOL_CONTENT_MAX] + f"\n…(截断，原长 {len(content)} 字)"


def _sanitize_msg(m: dict) -> dict | None:
    """规范化单条消息；非法则丢弃。"""
    if not isinstance(m, dict):
        return None
    role = m.get("role")
    if role not in ("user", "assistant", "tool", "system"):
        return None

    out: dict[str, Any] = {"role": role}

    if role == "tool":
        tid = m.get("tool_call_id")
        if not tid:
            return None
        out["tool_call_id"] = tid
        out["content"] = _truncate_tool_content(m.get("content") or "")
        if m.get("name"):
            out["name"] = m["name"]
        return out

    content = m.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)
    out["content"] = content

    if role == "assistant":
        tcs = m.get("tool_calls")
        if tcs:
            out["tool_calls"] = tcs
        # reasoning_content 仅用于同 turn DeepSeek 续写，落盘可保留但截断
        rc = m.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            out["reasoning_content"] = rc[:2000] if len(rc) > 2000 else rc

    if role in ("user", "assistant") and not out.get("content") and not out.get("tool_calls"):
        return None
    return out


def repair_tool_chain(msgs: list[dict]) -> list[dict]:
    """保证 tool 消息紧跟带匹配 tool_calls 的 assistant，否则 DeepSeek 400。

    截断/摘要/旧 memory 迁移后容易留下孤儿 tool；此处在 load/for_llm/persist 统一修复。
    """
    if not msgs:
        return []
    repaired: list[dict] = []
    i = 0
    n = len(msgs)
    while i < n:
        m = msgs[i]
        role = m.get("role")
        if role == "tool":
            # 孤儿 tool：前面没有完整 assistant+tool_calls
            i += 1
            continue
        if role == "assistant" and m.get("tool_calls"):
            ids = [tc.get("id") for tc in (m.get("tool_calls") or []) if tc.get("id")]
            j = i + 1
            found: dict[str, dict] = {}
            while j < n and msgs[j].get("role") == "tool":
                tid = msgs[j].get("tool_call_id")
                if tid in ids and tid not in found:
                    found[tid] = msgs[j]
                j += 1
            if ids and len(found) == len(ids):
                repaired.append(m)
                for tid in ids:
                    repaired.append(found[tid])
            else:
                # 不完整：降级为纯文本，避免 API 拒识
                plain = {
                    "role": "assistant",
                    "content": (m.get("content") or "").strip() or "[此前调用过工具]",
                }
                repaired.append(plain)
            i = j
            continue
        repaired.append(m)
        i += 1
    return repaired


def _summarize_for_condense(msgs: list[dict]) -> str:
    """把一段旧消息压成摘要文本。"""
    tools_used: list[str] = []
    user_bits: list[str] = []
    asst_bits: list[str] = []
    for m in msgs:
        role = m.get("role")
        if role == "user":
            c = (m.get("content") or "").replace("\n", " ").strip()
            if c:
                user_bits.append(c[:80])
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    name = tc.get("function", {}).get("name") or "?"
                except Exception:
                    name = "?"
                tools_used.append(name)
            c = (m.get("content") or "").replace("\n", " ").strip()
            if c:
                asst_bits.append(c[:80])
        elif role == "tool":
            pass
    parts = ["[对话摘要]"]
    if user_bits:
        parts.append("用户：" + " | ".join(user_bits[:4]))
    if tools_used:
        # 去重保序
        seen = set()
        uniq = []
        for t in tools_used:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        parts.append("曾调用工具：" + ", ".join(uniq))
    if asst_bits:
        parts.append("回复要点：" + " | ".join(asst_bits[:3]))
    return "\n".join(parts)


class Transcript:
    """落盘结构化对话历史。"""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.load()

    def load(self) -> None:
        try:
            if os.path.isfile(TRANSCRIPT_PATH):
                with open(TRANSCRIPT_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                ts = float(data.get("updated_at") or 0)
                if ts and (time.time() - ts) > TRANSCRIPT_TTL_SEC:
                    self.messages = []
                    return
                cleaned = []
                for m in data.get("messages") or []:
                    sm = _sanitize_msg(m)
                    if sm and sm.get("role") != "system":
                        cleaned.append(sm)
                self.messages = repair_tool_chain(cleaned)[-TRANSCRIPT_MAX_MSGS:]
                return

            # 迁移旧扁平 memory
            if os.path.isfile(LEGACY_MEMORY_PATH):
                with open(LEGACY_MEMORY_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                ts = float(data.get("updated_at") or 0)
                if ts and (time.time() - ts) > TRANSCRIPT_TTL_SEC:
                    return
                cleaned = []
                for m in data.get("messages") or []:
                    if not isinstance(m, dict):
                        continue
                    role = m.get("role")
                    content = m.get("content")
                    if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                        # 去掉历史【工具结果】大块可保留，便于追问
                        cleaned.append({"role": role, "content": content})
                self.messages = cleaned[-TRANSCRIPT_MAX_MSGS:]
                if self.messages:
                    self.persist()
        except Exception:
            self.messages = []

    def persist(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            # 落盘前截断 tool content + 修复 tool 链
            stored = []
            for m in self.messages[-TRANSCRIPT_MAX_MSGS:]:
                sm = _sanitize_msg(m)
                if sm:
                    stored.append(sm)
            stored = repair_tool_chain(stored)
            self.messages = stored
            if not stored:
                if os.path.isfile(TRANSCRIPT_PATH):
                    os.remove(TRANSCRIPT_PATH)
                return
            payload = {"updated_at": time.time(), "messages": stored}
            tmp = TRANSCRIPT_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, TRANSCRIPT_PATH)
        except Exception:
            pass

    def for_llm(self) -> list[dict]:
        """供 LLM 的历史：把已完成的 tool 回合压成纯文本。

        不能把历史 tool_calls/tool 原样回放——缺 reasoning_content 或链被截断时
        DeepSeek 会 400（Messages with role 'tool' must be a response to ...）。
        当前 turn 的 tool 协议仍由 agent.handle 循环现场组装。
        """
        repaired = repair_tool_chain(self.messages)
        out: list[dict] = []
        i = 0
        while i < len(repaired):
            m = repaired[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                names: list[str] = []
                for tc in m.get("tool_calls") or []:
                    try:
                        names.append(tc.get("function", {}).get("name") or "?")
                    except Exception:
                        names.append("?")
                bits: list[str] = []
                j = i + 1
                while j < len(repaired) and repaired[j].get("role") == "tool":
                    bits.append(
                        _truncate_tool_content(repaired[j].get("content") or "")[:800]
                    )
                    j += 1
                content = (m.get("content") or "").strip()
                parts = []
                if content:
                    parts.append(content)
                if names:
                    parts.append("【曾调用】" + ", ".join(names))
                if bits:
                    parts.append("【工具结果】\n" + "\n---\n".join(bits))
                out.append({
                    "role": "assistant",
                    "content": "\n\n".join(parts) or "[此前调用过工具]",
                })
                i = j
                continue
            if m.get("role") == "tool":
                i += 1
                continue
            cm = {"role": m["role"], "content": m.get("content") or ""}
            out.append(cm)
            i += 1
        return out

    def append_messages(self, msgs: list[dict]) -> None:
        for m in msgs:
            sm = _sanitize_msg(m)
            if sm and sm.get("role") != "system":
                self.messages.append(sm)
        self.messages = repair_tool_chain(self.messages)
        if len(self.messages) > TRANSCRIPT_MAX_MSGS:
            self.condense(keep_recent=TRANSCRIPT_MAX_MSGS // 2)
        else:
            self.persist()

    def clear(self) -> None:
        self.messages = []
        self.persist()

    def condense(self, keep_recent: int = 4) -> None:
        """压缩旧消息为一条摘要，保留最近 keep_recent 条（对齐到非 tool 边界）。"""
        if keep_recent < 1:
            keep_recent = 1
        msgs = repair_tool_chain(self.messages)
        if len(msgs) <= keep_recent:
            self.messages = msgs
            self.persist()
            return
        # 避免从 tool 消息切开：起点前移到 user/assistant
        cut = len(msgs) - keep_recent
        while cut < len(msgs) and msgs[cut].get("role") == "tool":
            cut += 1
        if cut >= len(msgs):
            cut = max(0, len(msgs) - 1)
        old = msgs[:cut]
        recent = msgs[cut:]
        summary = _summarize_for_condense(old)
        self.messages = repair_tool_chain([
            {"role": "assistant", "content": summary},
            *recent,
        ])
        self.persist()

    def maybe_condense_by_size(self) -> None:
        if len(self.messages) > TRANSCRIPT_MAX_MSGS:
            self.condense(keep_recent=16)
