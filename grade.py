"""批改 + BKT 更新

用法（被 main.py 或 listener 调用）:
    from grade import grade_answer
    result = grade_answer("通信原理题目...", "用户的解答...", subject="math", kp_name="矩阵与初等变换")
"""
from __future__ import annotations
import os, json
from dataclasses import dataclass

from config import DATA_DIR, DAILY_RECORD_DIR
from decide.router import call_llm

from bkt import BKTLogger, KCState


@dataclass
class GradeResult:
    is_correct: bool
    feedback: str
    kp_name: str = ""
    subject: str = ""
    p_mastery_before: float = 0.0
    p_mastery_after: float = 0.0
    credit: float | None = None
    item_type: str = "unknown"


def _get_bkt_log():
    return BKTLogger(os.path.join(DATA_DIR, "answer-log.jsonl"))


def _detect_item_type(question: str) -> str:
    """粗分 MCQ / blank / proof_outline / open，供题型 G 与 Δ 帽使用。"""
    q = question or ""

    # blank 检测（下划线 / 填空标记）
    blank_markers = ("____", "______", "（  ）", "________", "填空")
    if any(m in q for m in blank_markers):
        return "blank"

    # proof_outline 检测（强信号词）
    proof_markers = ("求证", "证毕", "证明题", "试证", "请证明", "推导过程")
    if any(m in q for m in proof_markers):
        return "proof_outline"

    # 原 MCQ 检测逻辑
    markers = (
        "A.",
        "B.",
        "C.",
        "D.",
        "A．",
        "B．",
        "C．",
        "D．",
        "（A）",
        "(A)",
        "选择题",
        "单选",
    )
    hits = sum(1 for m in ("A.", "B.", "C.", "D.", "A．", "B．", "C．", "D．") if m in q)
    if hits >= 3 or ("选择题" in q) or ("单选" in q):
        return "mcq"
    if any(m in q for m in markers) and hits >= 2:
        return "mcq"
    return "open"


def _find_reference_answer(kp_name: str) -> str:
    """从 YAML 种子中按知识点匹配参考答案。"""
    if not kp_name:
        return ""
    try:
        import yaml
        structured_dir = os.path.join(DAILY_RECORD_DIR, "structured")
        if not os.path.isdir(structured_dir):
            return ""
        for subj_dir in os.listdir(structured_dir):
            subj_path = os.path.join(structured_dir, subj_dir)
            if not os.path.isdir(subj_path):
                continue
            for fname in sorted(os.listdir(subj_path)):
                if not fname.endswith((".yaml", ".yml")):
                    continue
                with open(os.path.join(subj_path, fname), encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if not isinstance(data, list):
                        continue
                    for entry in data:
                        if kp_name in entry.get("kp", []) and entry.get("answer", "TBD") != "TBD":
                            return entry["answer"]
    except Exception:
        pass
    return ""


def _infer_subject(explicit: str, kp_name: str) -> str:
    if explicit in ("math", "comm", "review"):
        return "math" if explicit == "review" else explicit
    try:
        path = os.path.join(DATA_DIR, "last_push.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                subj = (json.load(f).get("subject") or "").strip()
            if subj in ("math", "comm"):
                return subj
            if subj == "review":
                return "math"
    except Exception:
        pass
    # 按能 resolve 到哪边猜
    try:
        from learner.kp_registry import resolve_kp
        if resolve_kp("math", kp_name):
            return "math"
        if resolve_kp("comm", kp_name):
            return "comm"
    except Exception:
        pass
    return "math"


def _parse_grade_verdict(raw: str) -> tuple[bool, float | None]:
    """从 LLM 批改正文解析 (is_correct, credit)。

    只看前几行「正确与否」区，避免评语里出现「不正确/部分正确」误伤。
    「不正确」不得因含「正确」二字被判对。
    """
    lines = [ln.strip() for ln in (raw or "").split("\n") if ln.strip()]
    head = "\n".join(lines[:4])
    first = lines[0] if lines else ""
    # 优先看明确的「正确与否：…」行
    verdict_line = first
    for ln in lines[:4]:
        if "正确与否" in ln or ln.startswith("判定") or ln.startswith("结果"):
            verdict_line = ln
            break
    if "部分正确" in verdict_line or (
        "部分正确" in head and "正确与否" not in head
    ):
        return False, 0.5
    neg = ("不正确", "错误", "不对", "未掌握", "答错")
    if any(n in verdict_line for n in neg):
        return False, None
    if "正确" in verdict_line:
        return True, None
    # 无明确 verdict：保守判错，避免空回复假正确
    return False, None


def grade_answer(
    question: str,
    user_answer: str,
    kp_name: str = "",
    subject: str = "",
) -> GradeResult:
    """批改用户作答，更新 BKT（按考纲 L2），返回结果。"""
    q = (question or "").strip()
    ua = (user_answer or "").strip()
    if not q:
        return GradeResult(
            is_correct=False,
            feedback="批改失败：题目为空。",
            kp_name=kp_name or "未分类",
            subject=subject or "math",
            item_type="unknown",
        )
    if not ua:
        return GradeResult(
            is_correct=False,
            feedback="未作答。请提交具体解答后再批改。",
            kp_name=kp_name or "未分类",
            subject=subject or "math",
            item_type=_detect_item_type(q),
        )

    ref_answer = _find_reference_answer(kp_name)
    ref_block = f"\n参考答案：{ref_answer}" if ref_answer else ""

    system = (
        "你是一个严格的考研批卷老师。判断用户解答是否正确（含部分正确）。\n"
        "输出格式：\n正确与否：正确/部分正确/错误\n评语：...\n涉及知识点：...\n\n"
        "书写格式：行内公式只用 $...$；块公式用 $$...$$；禁止 \\(...\\)。\n"
        "「涉及知识点」请尽量写考纲条目名（短），不要罗列一长串并列概念。"
    )
    prompt = f"题目：{q}\n\n用户解答：{ua}{ref_block}"
    raw = call_llm(system, prompt, "grade")
    from math_format import normalize_markdown_body
    raw = normalize_markdown_body(raw)

    # 解析结果
    is_correct, credit = _parse_grade_verdict(raw)

    # LLM 抽出的自由知识点（仅作 hint）
    extracted_hint = ""
    for line in raw.split("\n"):
        if "知识点" in line or "涉及" in line:
            extracted_hint = (
                line.split("：")[-1].strip() if "：" in line else line.split(":")[-1].strip()
            )
            break

    subj = _infer_subject(subject, kp_name or extracted_hint)
    try:
        from learner.kp_registry import normalize_kp_for_grade
        extracted_kp = normalize_kp_for_grade(
            subj,
            extracted_hint,
            preferred=kp_name,
        )
    except Exception:
        extracted_kp = (kp_name or extracted_hint or "").strip() or None

    if not extracted_kp:
        extracted_kp = kp_name or "未分类"

    item_type = _detect_item_type(q)

    # BKT 更新：必须恢复完整 state（opportunity/streak/due），禁止只灌 float
    bkt = _get_bkt_log()
    mastery_before = 0.2
    mastery_after = 0.2
    try:
        kc = bkt.get_kp_mastery("wx_123", extracted_kp)
        if kc is None:
            kc = KCState()
        else:
            kc = KCState.from_dict(kc.to_dict())
        mastery_before = kc.p_mastery
        # 部分正确：correct=True + credit=0.5（update 内缩 Δ⁺）；全对/全错走 boolean
        rec_correct = True if credit is not None else is_correct
        try:
            bkt.record(
                "wx_123",
                extracted_kp,
                rec_correct,
                kc,
                subject=subj,
                item_type=item_type,
                credit=credit,
            )
        except TypeError:
            bkt.record("wx_123", extracted_kp, is_correct, kc)
        mastery_after = kc.p_mastery
    except Exception as e:
        print(f"[grade] BKT update failed: {e}")

    # 答错（非部分正确）→ 轻微提高出题权重
    if credit is None and not is_correct and extracted_kp and extracted_kp != "未分类":
        try:
            from learner.weights_ops import bump_kp_weight
            bump_kp_weight(
                subj,
                extracted_kp,
                reason=f"grade_incorrect:{extracted_kp}",
            )
        except Exception as e:
            print(f"[grade] weight bump skipped: {e}")

    return GradeResult(
        is_correct=is_correct,
        feedback=raw,
        kp_name=extracted_kp,
        subject=subj,
        p_mastery_before=mastery_before,
        p_mastery_after=mastery_after,
        credit=credit,
        item_type=item_type,
    )
