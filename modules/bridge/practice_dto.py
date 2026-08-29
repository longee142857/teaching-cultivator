"""Practice shell DTO — map store pushes/items → teaching-shell.html shapes."""
from __future__ import annotations

import re
from typing import Any, Optional

# Frontend three-slot desk (DingTalk deep-link windows).
SLOT_SPECS: list[dict[str, str]] = [
    {
        "kind": "math",
        "label": "高等数学",
        "window": "08:00–12:00",
        "windowKey": "morning",
        "subjects": "math,数学一,高等数学",
    },
    {
        "kind": "comm",
        "label": "通信原理",
        "window": "12:00–18:00",
        "windowKey": "afternoon",
        "subjects": "comm,通信原理",
    },
    {
        "kind": "review",
        "label": "复习巩固",
        "window": "18:00–22:00",
        "windowKey": "evening",
        "subjects": "review,错题复盘,复习巩固",
    },
]

_SUBJECT_LABEL = {
    "math": "高等数学",
    "数学一": "高等数学",
    "高等数学": "高等数学",
    "comm": "通信原理",
    "通信原理": "通信原理",
    "review": "复习巩固",
    "错题复盘": "复习巩固",
    "复习巩固": "复习巩固",
}

_KATEX_RE = re.compile(
    r"\$\$([\s\S]+?)\$\$|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]",
    re.MULTILINE,
)
_TITLE_RE = re.compile(r"^#+\s+(.+)$", re.MULTILINE)
_WS_RE = re.compile(r"\s+")


def public_item_id(item_id: int | str) -> str:
    """Stable public id for deep links / shell state (``i{n}``)."""
    s = str(item_id).strip()
    if s.startswith("i") and s[1:].isdigit():
        return s
    if s.isdigit():
        return f"i{s}"
    return s


def parse_item_id(raw: str | int | None) -> Optional[int]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("i") and s[1:].isdigit():
        return int(s[1:])
    if s.isdigit():
        return int(s)
    return None


def parse_push_id(raw: str | int | None) -> Optional[int]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in ("dingtalk", "expired", "bad"):
        return None
    if s.isdigit():
        return int(s)
    return None


def subject_kind(subject: str, slot: str = "") -> str:
    blob = f"{(slot or '').strip()} {(subject or '').strip()}".lower()
    for spec in SLOT_SPECS:
        for alias in spec["subjects"].split(","):
            a = alias.strip().lower()
            if a and a in blob:
                return spec["kind"]
    # fallback by common codes
    sub = (subject or "").strip().lower()
    if sub in ("math", "数学一", "高等数学"):
        return "math"
    if sub in ("comm", "通信原理"):
        return "comm"
    if sub in ("review", "错题复盘", "复习巩固"):
        return "review"
    return "math"


def subject_label(subject: str, kind: str = "") -> str:
    s = (subject or "").strip()
    if s in _SUBJECT_LABEL:
        return _SUBJECT_LABEL[s]
    for spec in SLOT_SPECS:
        if spec["kind"] == kind:
            return spec["label"]
    return s or "练习"


def extract_katex(question: str) -> str:
    q = question or ""
    m = _KATEX_RE.search(q)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def extract_title(question: str, kp: str = "") -> str:
    q = (question or "").strip()
    m = _TITLE_RE.search(q)
    if m:
        return m.group(1).strip()[:48]
    # first non-empty non-formula line
    for line in q.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("$$") or line.startswith("\\"):
            continue
        if line.startswith("$"):
            continue
        return line[:48]
    kp = (kp or "").strip()
    return (kp.split("·")[0].strip() if kp else "练习题")[:48]


_OPTION_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?([A-D])(?:\*\*)?[\.．、:：\)]\s*(.+?)(?=\n\s*(?:\*\*)?[A-D](?:\*\*)?[\.．、:：\)]|\n\n|\Z)",
    re.S | re.I,
)


def extract_options(question: str) -> list[dict[str, str]]:
    """A–D choices for MCQ stems (letter + text, math kept)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _OPTION_LINE_RE.finditer(question or ""):
        letter = (m.group(1) or "").upper()
        text = (m.group(2) or "").strip()
        text = re.sub(r"[ \t]+\n", "\n", text).strip()
        if not letter or not text or letter in seen:
            continue
        seen.add(letter)
        out.append({"letter": letter, "text": text[:400]})
    return out


def extract_stem(question: str) -> str:
    """Stem for the desk. Keep math delimiters so the shell can KaTeX-render the full problem."""
    q = (question or "").strip()
    q = re.sub(r"^#+\s+.+$", "", q, flags=re.MULTILINE)
    q = _OPTION_LINE_RE.sub("", q)
    q = re.sub(r"[ \t]+\n", "\n", q)
    q = re.sub(r"\n{3,}", "\n\n", q).strip()
    return q[:2000] if q else "请完成本题作答。"


def explain_from_solution(solution: Any, answer: str = "") -> str:
    sol = solution if isinstance(solution, dict) else {}
    steps = sol.get("steps") or []
    parts: list[str] = []
    for st in steps:
        if isinstance(st, dict):
            t = (st.get("text") or "").strip()
        else:
            t = str(st or "").strip()
        if t:
            parts.append(t)
    final = (sol.get("final_answer") or answer or "").strip()
    if final:
        parts.append(f"参考答案：{final}")
    if parts:
        return " ".join(parts)[:1200]
    if answer:
        return f"参考要点：{answer}"[:800]
    return "本题讲解尚未结构化入库；可稍后接入讲师 agent。"


def comments_for_item(*, explain: str, answer: str = "") -> tuple[str, str]:
    ok = "步骤与结论正确。"
    bad = "结论或步骤有偏差，请对照参考要点复查。"
    if answer:
        bad = f"结论偏了。可对照参考：{answer[:80]}"
    if explain and "夹逼" in explain:
        bad = "结论偏了。注意夹逼两端是否同趋于同一值。"
    return ok, bad


def push_to_shell_item(
    row: dict[str, Any],
    *,
    backlog: bool = False,
    answered: bool | None = None,
) -> dict[str, Any]:
    """One store push/item row → shell item DTO (no answer key leaked as truth)."""
    item_id = int(row.get("item_id") or row.get("id") or 0)
    push_id = row.get("push_id")
    if push_id is None and "id" in row and row.get("question"):
        # already a push_row
        push_id = row.get("id")
    question = row.get("question") or ""
    kp = (row.get("kp") or "").strip()
    subject_raw = (row.get("subject") or "").strip()
    slot = (row.get("slot") or "").strip()
    kind = subject_kind(subject_raw, slot)
    solution = row.get("solution") or {}
    answer = (row.get("answer") or "").strip()
    # Do not put raw answer into client DTO; only soft comments/explain.
    explain = explain_from_solution(solution, answer="")
    # Prefer solution narrative; if empty, soft explain without final key
    if not explain or explain.startswith("本题讲解"):
        explain = explain_from_solution(solution, answer=answer) if solution else (
            "完成本题后可在结果页查看批改反馈。"
        )
    comment_ok, comment_bad = comments_for_item(explain=explain, answer="")
    ans_flag = row.get("answered") if answered is None else answered
    options = extract_options(question)
    title = extract_title(question, kp)
    stem = extract_stem(question)
    if title and stem.startswith(title):
        rest = stem[len(title) :].lstrip(" \t\n：:·。.")
        if rest:
            stem = rest
    out: dict[str, Any] = {
        "id": public_item_id(item_id),
        "itemId": item_id,
        "pushId": int(push_id) if push_id is not None else None,
        "kind": kind,
        "subject": subject_label(subject_raw, kind),
        "kp": kp or "未分类",
        "title": title,
        "stem": stem,
        "katex": extract_katex(question),
        "options": options,
        "commentOk": comment_ok,
        "commentBad": comment_bad,
        "explain": explain,
        "day": row.get("day") or row.get("date") or "",
        "backlog": bool(backlog),
        "fromBank": bool(row.get("from_bank") or row.get("fromBank")),
        "answered": bool(ans_flag),
        "difficulty": row.get("difficulty") or "",
        "slot": slot,
    }
    return out


def empty_slots() -> list[dict[str, Any]]:
    return [
        {
            "kind": s["kind"],
            "label": s["label"],
            "window": s["window"],
            "windowKey": s["windowKey"],
            "itemId": None,
            "pushId": None,
        }
        for s in SLOT_SPECS
    ]


def build_slots(items_by_kind: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in SLOT_SPECS:
        it = items_by_kind.get(s["kind"])
        out.append(
            {
                "kind": s["kind"],
                "label": s["label"],
                "window": s["window"],
                "windowKey": s["windowKey"],
                "itemId": it["id"] if it else None,
                "pushId": it.get("pushId") if it else None,
            }
        )
    return out


def normalize_answer_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("−", "-").replace("–", "-")
    t = _WS_RE.sub("", t)
    return t


__all__ = [
    "SLOT_SPECS",
    "build_slots",
    "comments_for_item",
    "empty_slots",
    "explain_from_solution",
    "extract_katex",
    "extract_options",
    "extract_stem",
    "extract_title",
    "normalize_answer_text",
    "parse_item_id",
    "parse_push_id",
    "public_item_id",
    "push_to_shell_item",
    "subject_kind",
    "subject_label",
]
