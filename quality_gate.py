"""出题契约质量闸（BIG-TEACH-010）

机器可判定的硬门槛：污染词、空稿、选项重复、答案字母不在选项、题干泄答。
编排层在 LLM 润色前后都可调用。
"""
from __future__ import annotations

import re
from typing import Iterable

# 统一污染 / 元思考词表（合并原 cultivate + math_format）
CONTAMINATION_MARKERS: tuple[str, ...] = (
    "重新出题",
    "我们调整一下",
    "为避免歧义",
    "多解",
    "其实应该",
    "我算错了",
    "选项重复",
    "但由于我之前",
    "为了贴合题目难度",
    "修改：将",
    "建议保持原题",
    "所以确定以下题目",
)

# 题干中出现则视为泄答
ANSWER_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"正确选项\s*[:：]\s*[A-D]", re.I),
    re.compile(r"答案\s*[:：]\s*[A-D]\b", re.I),
    re.compile(r"选\s*[A-D]\s*$", re.M),
    re.compile(r"<answer>", re.I),
)

_OPTION_LINE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?([A-D])(?:\*\*)?[\.．、:：\)]\s*(.+?)(?=\n\s*(?:\*\*)?[A-D](?:\*\*)?[\.．、:：\)]|\n\n|\Z)",
    re.S | re.I,
)
_ANSWER_LETTER = re.compile(
    r"(?:正确选项|答案|选)\s*[:：]?\s*([A-Z])\b|^([A-D])\s*$",
    re.I | re.M,
)


def text_contaminated(text: str, markers: Iterable[str] = CONTAMINATION_MARKERS) -> list[str]:
    if not text:
        return ["empty"]
    hits = [m for m in markers if m in text]
    return hits


def extract_mc_options(draft: str) -> dict[str, str]:
    """从题干提取 A-D 选项文本（去空白）。"""
    if not draft:
        return {}
    opts: dict[str, str] = {}
    for m in _OPTION_LINE.finditer(draft):
        letter = m.group(1).upper()
        body = re.sub(r"\s+", " ", (m.group(2) or "").strip())
        if body:
            opts[letter] = body
    return opts


def extract_answer_letter(answer: str) -> str | None:
    if not answer:
        return None
    m = _ANSWER_LETTER.search(answer.strip())
    if not m:
        # 纯字母开头
        head = answer.strip()[:8]
        m2 = re.match(r"^([A-D])\b", head, re.I)
        return m2.group(1).upper() if m2 else None
    return (m.group(1) or m.group(2) or "").upper() or None


def check_draft_answer(draft: str, answer: str, *, item_form: str = "") -> list[str]:
    """返回问题列表；空列表表示通过。

    item_form 为 "blank" 或 "proof_outline" 时跳过 MCQ 选项检查。
    """
    issues: list[str] = []
    if not (draft or "").strip():
        issues.append("empty_draft")
    if not (answer or "").strip() or len(answer.strip()) < 4:
        issues.append("empty_or_short_answer")

    for part, label in ((draft, "draft"), (answer, "answer")):
        hits = text_contaminated(part or "")
        # empty 已单独报
        hits = [h for h in hits if h != "empty"]
        for h in hits:
            issues.append(f"contaminate_{label}:{h}")

    d = draft or ""
    for pat in ANSWER_LEAK_PATTERNS:
        if pat.search(d):
            issues.append("answer_leak_in_draft")
            break

    # 对非 MCQ 题型跳过选项检查（blank/proof 无选项）
    if item_form in ("blank", "proof_outline"):
        return issues

    opts = extract_mc_options(d)
    if len(opts) >= 2:
        # 选项正文重复
        seen: dict[str, str] = {}
        for letter, body in opts.items():
            key = body.lower()
            if key in seen:
                issues.append(f"duplicate_option:{seen[key]}={letter}")
            else:
                seen[key] = letter
        letter = extract_answer_letter(answer or "")
        if letter and letter not in opts:
            issues.append(f"answer_letter_not_in_options:{letter}")
        if len(opts) >= 4 and not letter:
            # 四选一却抽不出答案字母
            issues.append("mcq_missing_answer_letter")

    return issues


def looks_contaminated(answer: str) -> bool:
    """兼容旧 cultivate._answer_looks_contaminated。"""
    if not answer or len(answer.strip()) < 8:
        return True
    return bool(text_contaminated(answer))
