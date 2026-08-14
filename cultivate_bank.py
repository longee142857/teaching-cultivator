# -*- coding: utf-8 -*-
"""分时段预生成：每槽最多 1 道 → ready 题库（不推送）。"""
from __future__ import annotations

from typing import Any

from learner.context import bind_owner_schedule
from learner.db import get_store
from learner.item_bank import (
    bank_quota,
    select_gap_spec,
    structure_item_via_llm,
    validate_bank_payload,
)


def pregenerate_one(subject: str, *, max_items: int = 1) -> dict[str, Any]:
    """调度入口。硬约束：max_items 必须为 1。"""
    if int(max_items) != 1:
        return {"ok": False, "error": "max_items_must_be_1", "subject": subject}
    subject = (subject or "").strip().lower()
    if subject not in ("math", "comm", "review"):
        return {"ok": False, "error": "bad_subject", "subject": subject}

    with bind_owner_schedule():
        return _pregenerate_one_inner(subject)


MAX_GAP_ATTEMPTS = 3


def _pregenerate_one_inner(subject: str) -> dict[str, Any]:
    store = get_store()
    if store.count_ready(subject) >= bank_quota(subject):
        return {
            "ok": True,
            "skipped": True,
            "reason": "quota_full",
            "ready": store.count_ready(subject),
            "subject": subject,
        }

    # 单缺口出题失败（无 L3 / 生成空 / 质量闸拒）时回退次优缺口，
    # 避免最弱 KP 一直出不来导致整个科目池长期空转。
    skipped_kps: set[str] = set()
    last_error = "no_gap"
    for _ in range(MAX_GAP_ATTEMPTS):
        spec = select_gap_spec(subject, skip_kps=skipped_kps)
        if not spec:
            return {"ok": True, "skipped": True, "reason": last_error, "subject": subject}
        result = _author_spec(subject, spec)
        if result.get("ok"):
            return result
        kp = (spec.get("kp") or "").split("[")[0].strip()
        if kp:
            skipped_kps.add(kp)
        last_error = result.get("error") or "generate_failed"
    return {"ok": False, "error": last_error, "subject": subject}


def _author_spec(subject: str, spec: dict) -> dict[str, Any]:
    """对单个缺口规格出题；失败返回 ok=False，供上层回退次优缺口。"""
    store = get_store()
    force_kp = (spec.get("kp") or "").strip()
    force_tech = (spec.get("technique") or "").strip()

    from cultivate import (
        assess_state,
        decide,
        generate,
        get_last_answer,
        _last_ref_source,
        _last_item_form,
        _bkt_available,
    )
    from learner.kp_registry import parse_l3_from_reason
    from intervention import InterventionDecision

    if not _bkt_available:
        return {"ok": False, "error": "bkt_unavailable", "subject": subject}

    state = assess_state(subject)
    decision = decide(subject, state["bkt_log"])
    ability = getattr(decision, "ability_goal", "") or ""
    diff = getattr(decision, "difficulty", "intermediate") or "intermediate"
    dtype = decision.type if decision.type != "defer" else "push"

    if force_kp:
        # 强制 L2 时必须挂上 [l3=…]，否则 generate 在 RAG_STRICT 下直接 abort
        from learner.kp_registry import pick_l3, syllabus_subject, list_l3_for_l2
        from learner.ability_cycle import encode_ability_reason

        l2 = force_kp.split("[")[0].strip()
        weight_subj = syllabus_subject(subject)
        l3_id = pick_l3(weight_subj, l2) if l2 else None
        if not l3_id and l2 and not list_l3_for_l2(weight_subj, l2):
            # 缺口 KP 不在考纲 / 无 L3：回退 decide 已选 L3
            l3_id = parse_l3_from_reason(getattr(decision, "reason", "") or "")
        if not l3_id:
            return {
                "ok": False,
                "error": "no_l3_for_gap_kp",
                "subject": subject,
                "kp": l2,
            }
        reason = f"{l2} [l3={l3_id}]"
        if ability:
            reason = f"{reason} {encode_ability_reason(ability)}"
        decision = InterventionDecision(
            type=dtype, difficulty=diff, reason=reason, priority=3, ability_goal=ability
        )
    elif decision.type == "defer":
        return {"ok": False, "error": "defer", "reason": decision.reason, "subject": subject}

    content = generate(subject, decision, source="bank")
    if not content:
        return {"ok": False, "error": "generate_failed", "subject": subject, "kp": force_kp}

    answer = get_last_answer() or ""
    structured = structure_item_via_llm(content, answer, force_kp or decision.reason)
    techniques = list(structured.get("techniques") or [])
    if force_tech and force_tech not in techniques:
        techniques.insert(0, force_tech)
    if not techniques:
        techniques = ["core_method"]
    solution = structured.get("solution") or {
        "steps": [{"id": "s1", "text": answer or content[:200]}],
        "final_answer": answer[:500] if answer else "",
        "techniques_used": techniques[:],
    }
    if not (solution.get("steps") or []):
        solution["steps"] = [{"id": "s1", "text": answer or "见题干推导"}]
    cdps = structured.get("cdps") or []
    if len(cdps) < 2:
        cdps = [
            {
                "id": "cdp1",
                "prompt": "识别本题关键方法/定理",
                "expected": techniques[0],
                "technique": techniques[0],
                "depends_on": [],
            },
            {
                "id": "cdp2",
                "prompt": "执行关键步骤并得到结论",
                "expected": "正确推导",
                "technique": techniques[0],
                "depends_on": ["cdp1"],
            },
        ]

    err = validate_bank_payload(
        question=content, techniques=techniques, solution=solution, cdps=cdps
    )
    if err:
        return {"ok": False, "error": f"quality:{err}", "subject": subject, "kp": force_kp}

    kp = force_kp or (
        decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    )
    kp = kp.split("[")[0].strip()
    l3_id = parse_l3_from_reason(getattr(decision, "reason", "") or "") or ""

    item_id = store.insert_bank_item(
        subject=subject,
        question=content,
        answer=answer,
        difficulty=diff,
        kp=kp,
        l3_id=l3_id,
        item_form=_last_item_form or "",
        ability_goal=ability,
        ref_source=_last_ref_source or "",
        techniques=techniques,
        solution=solution,
        cdps=cdps,
        meta={"source": "pregen", "technique_hint": force_tech},
        status="ready",
    )
    return {
        "ok": True,
        "skipped": False,
        "item_id": item_id,
        "subject": subject,
        "kp": kp,
        "techniques": techniques,
        "ready": store.count_ready(subject),
    }


PREGEN_SLOTS: list[tuple[str, str]] = [
    ("01:00", "math"),
    ("02:30", "math"),
    ("04:00", "comm"),
    ("05:30", "math"),
    ("07:00", "comm"),
    ("11:00", "review"),
    ("13:00", "math"),
    ("16:30", "comm"),
    ("21:00", "fill"),
]


def run_pregen_slot(subject_or_fill: str) -> dict[str, Any]:
    if subject_or_fill != "fill":
        return pregenerate_one(subject_or_fill, max_items=1)
    store = get_store()
    candidates = []
    for subj in ("math", "comm", "review"):
        ready = store.count_ready(subj)
        q = bank_quota(subj)
        if ready < q:
            candidates.append((q - ready, subj))
    if not candidates:
        return {"ok": True, "skipped": True, "reason": "all_full"}
    candidates.sort(key=lambda x: -x[0])
    return pregenerate_one(candidates[0][1], max_items=1)
