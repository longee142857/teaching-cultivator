"""编排层：质检 + 文案（可带 memory digest）后再发（BIG-TEACH-010）

推送与对话出题共用 orchestrate_push。
完整 Agent tool-loop 留待后续增强；本闸用 digest + polish/orchestrate 模板。
"""
from __future__ import annotations

from typing import Any

from quality_gate import check_draft_answer, extract_answer_letter


def _memory_digest(max_chars: int = 600) -> str:
    try:
        from agent.memory_blocks import MemoryBlocks

        blocks = MemoryBlocks()
        parts = []
        phase = blocks.phase
        if phase:
            parts.append(f"phase={phase}")
        aq = blocks._data.get("active_question") or {}
        if aq.get("kp") or aq.get("preview"):
            parts.append(
                f"上一题kp={aq.get('kp','')} preview={(aq.get('preview') or '')[:120]}"
            )
        digest = (blocks._data.get("learner_digest") or "").strip()
        if digest:
            parts.append(digest[:400])
        text = "\n".join(parts).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _polish_or_orchestrate(
    draft: str,
    answer: str,
    *,
    difficulty: str,
    subject: str,
    kp: str,
    source: str,
) -> str:
    """优先走 orchestrate 模板（含 digest）；失败回退 polish。"""
    from prompts.prompt_builder import PromptBuilder
    from decide.router import call_llm
    from math_format import split_question_answer, normalize_markdown_body

    builder = PromptBuilder()
    digest = _memory_digest()
    try:
        system, user = builder.build_orchestrate(
            draft_body=draft,
            answer_body=answer,
            memory_digest=digest or "（无会话摘要）",
            subject=subject,
            kp=kp,
            source=source,
        )
        raw = call_llm(system, user, "orchestrate", difficulty)
        body, leaked = split_question_answer(raw)
        if leaked:
            print("[orchestrate] leaked answer — stripped")
        out = normalize_markdown_body(body) or ""
        if out.strip():
            return out
    except Exception as e:
        print(f"[orchestrate] orchestrate template failed: {e}")

    try:
        system, user = builder.build_polish(draft_body=draft, answer_body=answer)
        raw = call_llm(system, user, "polish", difficulty)
        body, leaked = split_question_answer(raw)
        if leaked:
            print("[orchestrate] polish leaked answer — stripped")
        return normalize_markdown_body(body) or normalize_markdown_body(draft)
    except Exception as e:
        print(f"[orchestrate] polish failed, use draft: {e}")
        return normalize_markdown_body(draft)


def orchestrate_push(
    artifact: dict[str, Any],
    *,
    subject: str = "",
    difficulty: str = "intermediate",
    source: str = "schedule",
    max_author_retries: int = 0,
    reauthor_fn=None,
) -> dict[str, Any]:
    """质检 → 文案 → 再质检发送稿。

    artifact 至少含 draft/answer；可选 kp。
    reauthor_fn: 可选 () -> dict 新 artifact，用于重试。
    """
    art = dict(artifact or {})
    attempts = 0
    last_issues: list[str] = []
    item_form = str(art.get("item_form") or "")

    while True:
        draft = (art.get("draft") or "").strip()
        answer = (art.get("answer") or "").strip()
        issues = check_draft_answer(draft, answer, item_form=item_form)
        last_issues = issues
        if issues:
            print(f"[orchestrate] quality reject: {issues}")
            if attempts < max_author_retries and callable(reauthor_fn):
                attempts += 1
                print(f"[orchestrate] re-author attempt {attempts}")
                new_art = reauthor_fn()
                if isinstance(new_art, dict) and (new_art.get("draft") or "").strip():
                    art.update(new_art)
                    continue
            return {
                "status": "reject",
                "content": "",
                "answer": answer,
                "reason": ";".join(issues),
                "issues": issues,
                "artifact": art,
            }

        kp = str(art.get("kp") or "")
        content = _polish_or_orchestrate(
            draft,
            answer,
            difficulty=difficulty,
            subject=subject,
            kp=kp,
            source=source,
        )
        # 发送稿再扫一遍泄答 / 污染
        send_issues = check_draft_answer(content, answer)
        # 发送稿允许无 <answer>；忽略 empty_or_short_answer 对 content 侧的误报
        send_issues = [
            i
            for i in send_issues
            if i not in ("empty_or_short_answer",)
            and not i.startswith("mcq_missing_answer_letter")
            and not i.startswith("answer_letter_not_in_options")
        ]
        # 对发送稿：空稿 / 污染 / 泄答 / 选项重复仍拦截
        send_issues = [
            i
            for i in send_issues
            if i == "empty_draft"
            or i.startswith("contaminate_draft")
            or i == "answer_leak_in_draft"
            or i.startswith("duplicate_option")
        ]
        if not (content or "").strip():
            send_issues.append("empty_sendable")
        # 发送正文若仍含答案字母明示
        if extract_answer_letter(content) and "正确选项" in content:
            send_issues.append("answer_leak_in_sendable")

        if send_issues:
            print(f"[orchestrate] sendable reject: {send_issues}")
            if attempts < max_author_retries and callable(reauthor_fn):
                attempts += 1
                new_art = reauthor_fn()
                if isinstance(new_art, dict) and (new_art.get("draft") or "").strip():
                    art.update(new_art)
                    continue
            # 回退：用已过闸的 draft 作为发送稿（仍无答案）
            fallback = draft
            fb_issues = [
                i
                for i in check_draft_answer(fallback, answer)
                if i.startswith("contaminate_draft") or i == "answer_leak_in_draft"
            ]
            if not fb_issues and fallback:
                return {
                    "status": "accept",
                    "content": fallback,
                    "answer": answer,
                    "reason": "fallback_draft_after_sendable_fail",
                    "issues": send_issues,
                    "artifact": art,
                }
            return {
                "status": "reject",
                "content": "",
                "answer": answer,
                "reason": ";".join(send_issues),
                "issues": send_issues,
                "artifact": art,
            }

        return {
            "status": "accept",
            "content": content,
            "answer": answer,
            "reason": "ok",
            "issues": [],
            "artifact": art,
        }
