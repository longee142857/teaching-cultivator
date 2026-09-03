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


def _sanitize_ref_source(content_subj: str, raw: str) -> str:
    """来源标签必须与内容科目一致；对不上留空。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if content_subj == "math":
        return s if "数学一" in s else ""
    if content_subj == "comm":
        return s if "通信原理" in s else ""
    return ""


def _author_spec(subject: str, spec: dict) -> dict[str, Any]:
    """对单个缺口规格出题；失败返回 ok=False，供上层回退次优缺口。"""
    store = get_store()
    force_kp = (spec.get("kp") or "").strip()
    force_tech = (spec.get("technique") or "").strip()
    content_subj = (spec.get("content_subject") or "").strip().lower()
    if subject == "review":
        from learner.kp_registry import content_subject_for_kp

        content_subj = content_subj or content_subject_for_kp(force_kp) or "math"
        gen_subject = content_subj
    else:
        gen_subject = subject
        content_subj = subject if subject in ("math", "comm") else content_subj

    from cultivate import (
        assess_state,
        decide,
        generate,
        get_last_answer,
        get_last_ref_source,
        get_last_item_form,
        _bkt_available,
    )
    from learner.kp_registry import parse_l3_from_reason
    from intervention import InterventionDecision

    if not _bkt_available:
        return {"ok": False, "error": "bkt_unavailable", "subject": subject}

    state = assess_state(gen_subject if gen_subject in ("math", "comm") else subject)
    decision = decide(subject, state["bkt_log"])
    ability = getattr(decision, "ability_goal", "") or ""
    diff = getattr(decision, "difficulty", "intermediate") or "intermediate"
    dtype = decision.type if decision.type != "defer" else "push"

    if force_kp:
        # 强制 L2 时必须挂上 [l3=…]，否则 generate 在 RAG_STRICT 下直接 abort
        from learner.kp_registry import pick_l3, list_l3_for_l2
        from learner.ability_cycle import encode_ability_reason

        l2 = force_kp.split("[")[0].strip()
        weight_subj = content_subj if content_subj in ("math", "comm") else gen_subject
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
        if content_subj in ("math", "comm"):
            reason = f"{reason} [content_subject={content_subj}]"
        decision = InterventionDecision(
            type=dtype, difficulty=diff, reason=reason, priority=3, ability_goal=ability
        )
    elif decision.type == "defer":
        return {"ok": False, "error": "defer", "reason": decision.reason, "subject": subject}

    content = generate(gen_subject, decision, source="bank")
    if not content:
        return {"ok": False, "error": "generate_failed", "subject": subject, "kp": force_kp}

    answer = get_last_answer() or ""
    ref_source = _sanitize_ref_source(content_subj, get_last_ref_source())
    item_form = get_last_item_form() or ""
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

    meta = {"source": "pregen", "technique_hint": force_tech, "content_subject": content_subj}
    try:
        from modules.capability import merge_irt_into_meta

        meta = merge_irt_into_meta(meta, kp=kp, difficulty=diff)
    except Exception as e:
        print(f"[cultivate_bank] irt meta skipped: {e}")

    item_id = store.insert_bank_item(
        subject=subject,
        question=content,
        answer=answer,
        difficulty=diff,
        kp=kp,
        l3_id=l3_id,
        item_form=item_form,
        ability_goal=ability,
        ref_source=ref_source,
        techniques=techniques,
        solution=solution,
        cdps=cdps,
        meta=meta,
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
    ("00:30", "math"),
    ("01:00", "math"),
    ("01:30", "comm"),
    ("02:00", "math"),
    ("02:30", "comm"),
    ("03:00", "review"),
    ("03:30", "review"),
    ("04:00", "fill"),
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


def sanitize_stored_ref_sources(store=None) -> dict[str, Any]:
    """清洗已入库题的串科来源（只改 ref_source，不动题干/已推送正文）。"""
    store = store or get_store()
    from learner.kp_registry import item_content_subject

    def _do(conn) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT * FROM items WHERE COALESCE(ref_source, '') != ''"
        ).fetchall()
        samples: list[dict] = []
        n = 0
        for r in rows:
            d = store._item_dict(r)
            cs = item_content_subject(d)
            old = (d.get("ref_source") or "").strip()
            new = _sanitize_ref_source(cs, old)
            if new == old:
                continue
            conn.execute(
                "UPDATE items SET ref_source=? WHERE id=?",
                (new, int(d["id"])),
            )
            n += 1
            if len(samples) < 12:
                samples.append(
                    {
                        "id": int(d["id"]),
                        "old": old,
                        "content_subject": cs,
                        "kp": d.get("kp") or "",
                    }
                )
        return {"ok": True, "cleared": n, "samples": samples}

    return store._txn(_do)
