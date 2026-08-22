"""批改 + BKT 更新

用法（被 main.py 或 listener 调用）:
    from grade import grade_answer
    result = grade_answer("通信原理题目...", "用户的解答...", subject="math", kp_name="矩阵与初等变换")
"""
from __future__ import annotations
import os, json, re
from dataclasses import dataclass

from config import DATA_DIR, DAILY_RECORD_DIR
from learner.context import current_user_id
from learner import paths as P
from decide.router import call_llm

from bkt import BKTLogger, KCState
import bkt as _bkt_module

# BIG-TEACH-012a #7a
CONFIDENCE_THRESHOLD = 0.8

# 设置 BKT overrides 路径（BIG-TEACH-012b #2）
from config import BKT_OVERRIDES_PATH as _bkt_ov_path
_bkt_module.BKT_OVERRIDES_PATH = _bkt_ov_path


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
    status: str = "applied"
    confidence: float = 0.0


def _get_bkt_log():
    from learner.bkt_db import DbBKTLogger
    return DbBKTLogger()


def _uid() -> str:
    return current_user_id()


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
    # DB 权威（BIG-TEACH-013）
    try:
        from learner.db import get_store
        from learner.context import current_user_id
        sid = current_user_id() or ""
    except Exception:
        sid = ""
    try:
        lp = get_store().get_latest_push(sid or None)
        if lp:
            subj = (lp.get("subject") or "").strip()
            if subj in ("math", "comm"):
                return subj
            if subj == "review":
                return "math"
    except Exception:
        pass
    # 旧文件兼容（迁移前）
    for path in (P.last_push_path(), P.public_last_class_path()):
        try:
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


# ── BIG-TEACH-012a #7a: Structured grading + verifier ──


def _parse_grade_json(raw: str) -> dict | None:
    """从 grade LLM 回复中提取结构化 JSON。"""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        result = json.loads(m.group())
        if result.get("verdict") in ("correct", "partial", "incorrect"):
            return result
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _call_grade_llm(
    question: str,
    user_answer: str,
    ref_answer: str = "",
    cdps: list | None = None,
) -> dict:
    """Grade LLM 返回结构化 verdict（可选 CDP 逐条判定）。"""
    ref_block = f"\n参考答案：{ref_answer}" if ref_answer else ""
    cdp_block = ""
    cdp_schema = ""
    if cdps:
        import json as _json
        cdp_block = "\n决策点列表（必须逐 id 判定）：\n" + _json.dumps(
            cdps, ensure_ascii=False
        )
        cdp_schema = (
            ', "cdp_results": [{"id":"cdp1","ok":true|false,'
            '"technique":"...","note":"..."}]'
        )
    system = (
        "你是一个严格的考研批卷老师。判断用户解答是否正确。\n"
        "以 JSON 格式输出，不要包含其他内容：\n"
        '{"verdict": "correct|partial|incorrect", "confidence": 0.0-1.0, '
        f'"explanation": "..."{cdp_schema}}}\n\n'
        "置信度说明：\n"
        "- 1.0: 完全确定，答案明确正确或错误\n"
        "- 0.8-0.9: 很确定\n"
        "- 0.5-0.7: 有些不确定，解答模糊\n"
        "- <0.5: 很不确定\n"
        "若给出了决策点，cdp_results 必须覆盖每一个 id，并填写 technique。\n"
        "书写格式：行内公式只用 $...$；块公式用 $$...$$；禁止 \\(...\\)。"
    )
    prompt = f"题目：{question}\n\n用户解答：{user_answer}{ref_block}{cdp_block}"
    raw = call_llm(system, prompt, "grade")
    from math_format import normalize_markdown_body
    raw = normalize_markdown_body(raw)

    parsed = _parse_grade_json(raw)
    if parsed:
        return {
            "verdict": parsed["verdict"],
            "confidence": float(parsed.get("confidence", 0.6)),
            "explanation": str(parsed.get("explanation") or "").strip(),
            "raw": raw,
            "from_fallback": False,
            "cdp_results": parsed.get("cdp_results") or [],
        }

    # Fallback: old text parser — uncertain only, never high enough to write BKT
    is_correct, credit = _parse_grade_verdict(raw)
    if is_correct and credit is None:
        verdict = "correct"
    elif credit == 0.5:
        verdict = "partial"
    else:
        verdict = "incorrect"
    return {
        "verdict": verdict,
        "confidence": 0.4,
        "raw": raw,
        "from_fallback": True,
        "cdp_results": [],
    }


def _parse_verify_json(raw: str) -> dict | None:
    """从 verify LLM 回复中提取结构化 JSON。"""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        result = json.loads(m.group())
        if "agrees" in result and "confidence" in result:
            return result
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _call_verify_llm(question: str, user_answer: str, grade_json: dict) -> dict:
    """Verifier LLM：检查批改是否存在误判。返回 {'agrees', 'confidence', 'reasoning'}。"""
    system = (
        "你是一个批改质量审查员。另一位老师已批改了一份学生解答，你需要检查是否存在误判。\n"
        "重点关注：是否过于严格？是否过于宽松？是否忽略了关键错误？\n\n"
        "以 JSON 格式输出，不要包含其他内容：\n"
        '{"agrees": true|false, "confidence": 0.0-1.0, "reasoning": "..."}\n\n'
        "agrees: 是否同意原批改的判定\n"
        "confidence: 你对自身判断的把握度"
    )
    prompt = (
        f"题目：{question}\n\n"
        f"用户解答：{user_answer}\n\n"
        f"原批改判定：{grade_json.get('verdict', '?')}\n"
        f"原批改解释：{grade_json.get('raw', '')[:500]}\n\n"
        "请检查原批改是否正确，输出 JSON。"
    )
    raw = call_llm(system, prompt, "verify_grade")

    parsed = _parse_verify_json(raw)
    if parsed:
        return {
            "agrees": bool(parsed["agrees"]),
            "confidence": float(parsed.get("confidence", 0.5)),
            "reasoning": parsed.get("reasoning", ""),
            "from_fallback": False,
        }
    # Fallback: uncertain — do not auto-agree into BKT writes
    return {
        "agrees": False,
        "confidence": 0.0,
        "reasoning": "parse fallback",
        "from_fallback": True,
    }


def _compute_effective_confidence(
    grade_conf: float,
    verify: dict,
    *,
    grade_fallback: bool = False,
) -> float:
    """合并 grade 与 verify 置信度。不一致 / 任一侧 fallback → 0。"""
    if grade_fallback or verify.get("from_fallback"):
        return 0.0
    if verify.get("agrees"):
        return min(grade_conf, verify.get("confidence", 0.0))
    return 0.0


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

    item_cdps: list = []
    try:
        from learner.db import get_store
        item = get_store().get_item_by_question(q, subject or "")
        if item:
            item_cdps = list(item.get("cdps") or [])
            if not ref_answer and item.get("answer"):
                ref_answer = item.get("answer") or ""
    except Exception:
        item_cdps = []

    # ── Structured grade LLM → verifier → apply/pending (BIG-TEACH-012a #7a) ──
    grade_json = _call_grade_llm(q, ua, ref_answer, cdps=item_cdps or None)
    verify_json = _call_verify_llm(q, ua, grade_json)
    effective_conf = _compute_effective_confidence(
        grade_json.get("confidence", 0.0),
        verify_json,
        grade_fallback=bool(grade_json.get("from_fallback")),
    )

    cdp_results: list = []
    aligned = True
    if item_cdps:
        from learner.item_bank import align_cdp_results
        cdp_results, aligned = align_cdp_results(
            item_cdps, grade_json.get("cdp_results") or []
        )
        if not aligned:
            # 缺条/错 id → 压低置信度，倾向 pending
            effective_conf = min(effective_conf, 0.5)

    raw = grade_json.get("raw", "")
    verdict = grade_json.get("verdict", "incorrect")
    if verdict == "correct":
        is_correct, credit = True, None
    elif verdict == "partial":
        is_correct, credit = False, 0.5
    else:
        is_correct, credit = False, None

    status = "applied" if effective_conf >= CONFIDENCE_THRESHOLD else "pending"

    # ── KP extraction from raw (backward compat: old text format) ──
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
        extracted_kp = normalize_kp_for_grade(subj, extracted_hint, preferred=kp_name)
    except Exception:
        extracted_kp = (kp_name or extracted_hint or "").strip() or None
    if not extracted_kp:
        extracted_kp = kp_name or "未分类"

    item_type = _detect_item_type(q)

    # ── BKT update（仅 applied 时更新 mastery；pending 直写日志不更新 state）──
    # 作答即唤醒：先 mark_answered，避免 silent 闸挡住 weights/BKT 写入
    try:
        from learner.roster import mark_answered

        mark_answered(_uid())
    except Exception as e:
        print(f"[grade] mark_answered skipped: {e}")

    bkt = _get_bkt_log()
    mastery_before = 0.2
    mastery_after = 0.2
    try:
        kc = bkt.get_kp_mastery(_uid(), extracted_kp)
        if kc is None:
            kc = KCState()
        else:
            kc = KCState.from_dict(kc.to_dict())
        mastery_before = kc.p_mastery

        if status == "applied":
            rec_correct = True if credit is not None else is_correct
            _kp_overrides = _bkt_module._load_bkt_overrides().get(extracted_kp, {})
            # 未分类不是有效 L2，不写 BKT 状态（权重 bump/decay 已跳过）
            if extracted_kp and extracted_kp != "未分类":
                try:
                    from learner.db import get_store
                    resolved = get_store().resolve_push_for_question(_uid(), q)
                    push_id = resolved[0] if resolved else None
                    item_id = resolved[1] if resolved else None
                except Exception:
                    push_id = item_id = None
                try:
                    bkt.record(
                        _uid(), extracted_kp, rec_correct, kc,
                        subject=subj, item_type=item_type, credit=credit,
                        status="applied", overrides=_kp_overrides,
                        push_id=push_id, item_id=item_id,
                        cdp_results=cdp_results or None,
                        confidence=round(effective_conf, 4),
                    )
                except TypeError:
                    bkt.record(_uid(), extracted_kp, is_correct, kc)
            mastery_after = kc.p_mastery

            # 答错（非部分正确）→ 轻微提高出题权重
            if credit is None and not is_correct and extracted_kp and extracted_kp != "未分类":
                try:
                    from learner.weights_ops import bump_kp_weight
                    # record_bkt=False：本函数已 bkt.record 记过答错，避免双重 BKT
                    bump_kp_weight(subj, extracted_kp,
                                   reason=f"grade_incorrect:{extracted_kp}",
                                   record_bkt=False)
                except Exception as e:
                    print(f"[grade] weight bump skipped: {e}")

            # 答对（含部分正确按 credit）→ 衰减出题权重（不低于 baseline，BIG-TEACH-012b #1）
            if (is_correct or (credit is not None and credit > 0)) and extracted_kp and extracted_kp != "未分类":
                try:
                    from learner.weights_ops import decay_kp_weight
                    decay_kp_weight(subj, extracted_kp, reason=f"grade_correct:{extracted_kp}")
                except Exception as e:
                    print(f"[grade] weight decay skipped: {e}")

            # 能力参数：BKT 写回后刷新域 η 快照（capability-prob 对齐）
            try:
                from modules.capability import refresh_after_grade

                refresh_after_grade(_uid(), persist_snapshot=True)
            except Exception as e:
                print(f"[grade] capability refresh skipped: {e}")
        else:
            # pending: 直写 answer-log，不更新 state；带 state 快照避免 get_kp_mastery 误回放
            from datetime import datetime, timezone
            pending_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "user_id": _uid(),
                "knowledge_point": extracted_kp,
                "correct": is_correct,
                "item_type": item_type,
                "mastery_before": round(mastery_before, 4),
                "mastery_after": round(mastery_before, 4),
                "update_applied": False,
                "update_reason": f"confidence {effective_conf:.2f} < threshold {CONFIDENCE_THRESHOLD}",
                "status": "pending",
                "confidence": round(effective_conf, 4),
                "state": kc.to_dict(),
            }
            if credit is not None:
                pending_entry["credit"] = credit
            if subj:
                pending_entry["subject"] = subj
            if cdp_results:
                pending_entry["cdp_results"] = cdp_results
            try:
                from learner.db import get_store
                store = get_store()
                resolved = store.resolve_push_for_question(_uid(), q)
                if resolved:
                    pending_entry["push_id"] = resolved[0]
                    pending_entry["item_id"] = resolved[1]
                store.add_attempt_entry(pending_entry)
                if cdp_results:
                    from learner.item_bank import learner_cdp_fail_summary

                    fail_sum = learner_cdp_fail_summary(cdp_results)
                    store.add_ability_snapshot(
                        _uid(),
                        {
                            "kp_failures": [extracted_kp] if not is_correct else [],
                            "technique_failures": fail_sum["technique_failures"],
                            "cdp_fail_ids": fail_sum["cdp_fail_ids"],
                            "at": pending_entry["ts"],
                            "status": "pending",
                            "cdp_aligned": aligned if item_cdps else None,
                        },
                    )
            except Exception as e:
                print(f"[grade] pending write failed: {e}")
            mastery_after = mastery_before
    except Exception as e:
        print(f"[grade] BKT update failed: {e}")

    return GradeResult(
        is_correct=is_correct,
        # 结构化 verdict 时 raw 是 JSON 串，优先给人读的 explanation
        feedback=grade_json.get("explanation") or raw,
        kp_name=extracted_kp,
        subject=subj,
        p_mastery_before=mastery_before,
        p_mastery_after=mastery_after,
        credit=credit,
        item_type=item_type,
        status=status,
        confidence=round(effective_conf, 4),
    )
