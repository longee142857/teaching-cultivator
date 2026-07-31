"""编排层：质检 + 文案（可带 memory digest）后再发（BIG-TEACH-010）

推送与对话出题共用 orchestrate_push。
完整 Agent tool-loop 留待后续增强；本闸用 digest + polish/orchestrate 模板。
"""
from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any

from quality_gate import check_draft_answer, extract_answer_letter

# BIG-TEACH-012a #7b: review_item (LLM reviewer for generated questions)

_REJECT_RAW_MAX = 8000


def _ops_rejects_path() -> str:
    from config import DATA_DIR

    return os.path.join(DATA_DIR, "ops", "rejects.jsonl")


def _truncate(text: str, n: int = _REJECT_RAW_MAX) -> str:
    s = text or ""
    if len(s) <= n:
        return s
    return s[:n] + f"\n...(truncated, orig_len={len(s)})"


def append_reject_event(event: dict[str, Any]) -> None:
    """Append one ops reject/bypass row for the monitor board."""
    try:
        path = _ops_rejects_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = dict(event)
        row.setdefault("ts", datetime.datetime.now().isoformat(timespec="seconds"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[orchestrate] reject log failed: {e}")


def _strip_review_noise(raw: str) -> str:
    """Peel markdown fences / thinking wrappers before JSON extract."""
    text = (raw or "").strip()
    if not text:
        return ""
    fence = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.I)
    return text.strip()


def _parse_review_json(raw: str) -> dict | None:
    cleaned = _strip_review_noise(raw)
    if not cleaned:
        return None
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return None
    blob = m.group()
    try:
        result = json.loads(blob)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        fixed = re.sub(r",\s*}", "}", blob)
        fixed = re.sub(r",\s*]", "]", fixed)
        result = json.loads(fixed)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _review_item(
    draft: str, answer: str, *,
    kp: str = "", subject: str = "",
    difficulty: str = "intermediate", item_form: str = "mcq",
) -> dict:
    """LLM 审查。返回 decision/issues/suggestion/raw/parse_ok。"""
    from decide.router import call_llm

    type_hint = {"mcq": "选择题", "blank": "填空题", "proof_outline": "证明/推导题"}.get(item_form, "题目")
    system = (
        "你是一个题目质量审查员。检查以下题目是否存在问题。\n"
        "检查要点：\n"
        "1. 题干是否有歧义或存在多解\n"
        "2. 难度与知识点是否匹配\n"
        "3. 答案与题干是否矛盾\n"
        "4. 题目表述是否清晰完整\n"
        "5. 选择题选项是否互斥且恰有一解\n\n"
        "以 JSON 格式输出，不要包含其他内容：\n"
        '{"decision": "accept|reject", "issues": ["问题1", ...], "suggestion": "改进建议"}'
    )
    prompt = (
        f"知识点：{kp}\n难度：{difficulty}\n题型：{type_hint}\n"
        f"题目：\n{draft}\n\n答案：\n{answer}\n\n请审查并输出 JSON。"
    )
    raw = call_llm(system, prompt, "review_item", difficulty) or ""

    result = _parse_review_json(raw)
    if result is not None:
        dec = result.get("decision", "reject")
        return {
            "decision": dec if dec in ("accept", "reject") else "reject",
            "issues": result.get("issues", []) if isinstance(result.get("issues"), list) else [],
            "suggestion": result.get("suggestion", ""),
            "raw": raw,
            "parse_ok": True,
        }
    return {
        "decision": "reject",
        "issues": ["review_item_parse_failed"],
        "suggestion": "审查输出无法解析，请重写题目",
        "raw": raw,
        "parse_ok": False,
    }


def _log_gate_event(
    *,
    kind: str,
    subject: str,
    difficulty: str,
    source: str,
    attempts: int,
    issues: list,
    draft: str,
    answer: str,
    artifact: dict,
    review_raw: str = "",
    suggestion: str = "",
) -> None:
    append_reject_event(
        {
            "kind": kind,
            "subject": subject,
            "difficulty": difficulty,
            "source": source,
            "attempts": attempts,
            "issues": list(issues or []),
            "kp": str(artifact.get("kp") or ""),
            "l3_id": str(artifact.get("l3_id") or artifact.get("unit_id") or ""),
            "item_form": str(artifact.get("item_form") or ""),
            "decision_type": str(artifact.get("decision_type") or ""),
            "draft": _truncate(draft),
            "answer": _truncate(answer),
            "review_raw": _truncate(review_raw, 4000),
            "suggestion": _truncate(suggestion, 1000),
        }
    )


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
    review_bypassed = False

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
            _log_gate_event(
                kind="reject",
                subject=subject,
                difficulty=difficulty,
                source=source,
                attempts=attempts,
                issues=issues,
                draft=draft,
                answer=answer,
                artifact=art,
            )
            return {
                "status": "reject",
                "content": "",
                "answer": answer,
                "reason": ";".join(issues),
                "issues": issues,
                "artifact": art,
            }

        kp = str(art.get("kp") or "")

        # BIG-TEACH-012a #7b: review_item (LLM reviewer)
        review = _review_item(
            draft, answer, kp=kp, subject=subject,
            difficulty=difficulty, item_form=item_form,
        )
        rev_issues = list(review.get("issues") or [])
        is_parse_failed = (
            rev_issues == ["review_item_parse_failed"]
            or (
                not review.get("parse_ok", True)
                and "review_item_parse_failed" in rev_issues
            )
        )

        if review.get("decision") == "reject":
            # Soft-bypass only pure parse failure — keep schedule alive
            if is_parse_failed:
                print(
                    "[orchestrate] review_item parse_failed — soft bypass "
                    "(continue polish; logged as review_parse_bypassed)"
                )
                review_bypassed = True
                _log_gate_event(
                    kind="review_parse_bypassed",
                    subject=subject,
                    difficulty=difficulty,
                    source=source,
                    attempts=attempts,
                    issues=["review_parse_bypassed"],
                    draft=draft,
                    answer=answer,
                    artifact=art,
                    review_raw=str(review.get("raw") or ""),
                    suggestion=str(review.get("suggestion") or ""),
                )
            else:
                print(f"[orchestrate] review_item reject: {rev_issues}")
                if attempts < max_author_retries and callable(reauthor_fn):
                    attempts += 1
                    print(f"[orchestrate] re-author attempt {attempts} (after review)")
                    new_art = reauthor_fn()
                    if isinstance(new_art, dict) and (new_art.get("draft") or "").strip():
                        art.update(new_art)
                        continue
                _log_gate_event(
                    kind="reject",
                    subject=subject,
                    difficulty=difficulty,
                    source=source,
                    attempts=attempts,
                    issues=rev_issues,
                    draft=draft,
                    answer=answer,
                    artifact=art,
                    review_raw=str(review.get("raw") or ""),
                    suggestion=str(review.get("suggestion") or ""),
                )
                return {
                    "status": "reject",
                    "content": "",
                    "answer": answer,
                    "reason": "review_item: " + ";".join(rev_issues),
                    "issues": rev_issues,
                    "artifact": art,
                }

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
                    "review_parse_bypassed": review_bypassed,
                }
            _log_gate_event(
                kind="reject",
                subject=subject,
                difficulty=difficulty,
                source=source,
                attempts=attempts,
                issues=send_issues,
                draft=draft,
                answer=answer,
                artifact=art,
            )
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
            "reason": "ok_review_parse_bypassed" if review_bypassed else "ok",
            "issues": ["review_parse_bypassed"] if review_bypassed else [],
            "artifact": art,
            "review_parse_bypassed": review_bypassed,
        }
