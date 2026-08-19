# -*- coding: utf-8 -*-
"""预出题库：缺口驱动选规格 + 结合模型抽题（BKT + η + 质量）。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from learner.db import get_store


def bank_quota(subject: str) -> int:
    subj = (subject or "").strip().lower()
    if subj == "review":
        return int(os.environ.get("BANK_QUOTA_REVIEW", "3"))
    if subj == "comm":
        return int(os.environ.get("BANK_QUOTA_COMM", "6"))
    return int(os.environ.get("BANK_QUOTA_MATH", "6"))


def live_fallback_enabled() -> bool:
    return os.environ.get("BANK_LIVE_FALLBACK", "0") == "1"


def _tech_boost_map(learner_id: str, *, limit: int = 30) -> dict[str, float]:
    from modules.capability.select import TECH_FAIL_BOOST

    out: dict[str, float] = {}
    try:
        sig = get_store().recent_ability_signals(learner_id, limit=limit)
        for row in sig.get("cdp_fail_recent") or []:
            kp = (row.get("kp") or "").strip()
            if kp:
                out[kp] = out.get(kp, 0.0) + TECH_FAIL_BOOST
    except Exception as e:
        print(f"[item_bank] tech_boost skipped: {e}")
    return out


def build_pick_context(
    subject: str,
    *,
    learner_id: str = "",
    days: int = 90,
) -> "Any":
    """组装结合模型 PickContext（weights + BKT + η + 技巧 + due）。"""
    from cultivate import _load_weights, _uid
    from learner.kp_registry import syllabus_subject, load_recent_picks
    from modules.capability import (
        PickContext,
        build_learner_params,
        weak_domain_boosts,
        eta_map_from_params,
    )

    lid = (learner_id or "").strip() or _uid()
    weight_subj = syllabus_subject(subject)
    weights = _load_weights()
    kp_w = (weights.get(weight_subj) or {}).get("kp_weights") or {}

    mastery: dict[str, float] = {}
    due: set[str] = set()
    try:
        from learner.bkt_db import DbBKTLogger

        bkt = DbBKTLogger()
        mastery = bkt.get_all_kp_mastery(lid) or {}
        if hasattr(bkt, "get_due_kps"):
            due = set(bkt.get_due_kps(lid) or set())
    except Exception as e:
        print(f"[item_bank] bkt for pick ctx skipped: {e}")

    domain_boosts: dict[str, float] = {}
    eta_map: dict[str, float] = {}
    assumptions: list[str] = []
    try:
        params = build_learner_params(
            get_store(), lid, learner_id=lid, days=days, persist_snapshot=False
        )
        eta_map = eta_map_from_params(params)
        domain_boosts = weak_domain_boosts(eta_map)
        assumptions = list(params.assumptions.to_list())
        # mastery 以 store/BKT 为准；params.mastery 可补洞
        for m in params.mastery:
            if m.kp and m.kp not in mastery:
                mastery[m.kp] = float(m.p_mastery)
    except Exception as e:
        print(f"[item_bank] η for pick ctx skipped: {e}")

    recent: list[str] = []
    try:
        recent = load_recent_picks(weight_subj) or []
    except Exception:
        recent = []

    return PickContext(
        learner_id=lid,
        subject=subject,
        mastery=mastery,
        kp_weights={str(k): float(v) for k, v in kp_w.items()},
        tech_boost=_tech_boost_map(lid),
        domain_boosts=domain_boosts,
        due_kps=due,
        recent_kps=list(recent),
        eta_by_domain=eta_map,
        assumptions=assumptions,
    )


def weak_kp_ranked(subject: str, limit: int = 8) -> list[tuple[str, float]]:
    """返回 [(kp, score)]，score 越大越优先补货/推送（结合模型）。"""
    from modules.capability import rank_kps

    ctx = build_pick_context(subject)
    return rank_kps(ctx, limit=limit)


def pick_technique_for_kp(kp: str) -> str:
    """近期该 KP 上失败最多的 technique；没有则空。"""
    try:
        sig = get_store().recent_ability_signals(
            __import__("learner.context", fromlist=["current_user_id"]).current_user_id(),
            limit=40,
        )
    except Exception:
        return ""
    counts: dict[str, int] = {}
    for row in sig.get("cdp_fail_recent") or []:
        if (row.get("kp") or "") != kp:
            continue
        t = (row.get("technique") or "").strip()
        if t:
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda x: x[1])[0]


def select_gap_spec(subject: str, *, skip_kps: set[str] | None = None) -> dict[str, str] | None:
    """选缺口最大的 (kp[, technique])；科目 ready 已满则 None。"""
    store = get_store()
    quota = bank_quota(subject)
    if store.count_ready(subject) >= quota:
        return None
    ranked = weak_kp_ranked(subject)
    if not ranked:
        return {"kp": "", "technique": "", "subject": subject}

    skip = {str(k).split("[")[0].strip() for k in (skip_kps or set())}
    best = None
    best_gap = -1
    for kp, score in ranked:
        if kp in skip:
            continue
        tech = pick_technique_for_kp(kp)
        have = store.count_ready(subject, kp=kp, technique=tech) if tech else store.count_ready(
            subject, kp=kp
        )
        gap = max(0, 1 - have)
        metric = gap * 10 + score * (1.0 / (1 + have))
        if metric > best_gap:
            best_gap = metric
            best = {"kp": kp, "technique": tech, "subject": subject}
    return best


def pick_for_push(
    subject: str,
    *,
    kp: str = "",
    technique: str = "",
    learner_id: str | None = None,
) -> dict | None:
    """结合模型抽 ready 题。

    在候选集上打分：quality′ + KP需求(BKT+η+技巧+due) + prefer_kp/tech 软加成。
    不再「无 KP 匹配就任意抽第一道」；decide 给出的 KP 只作偏好。
    """
    from modules.capability import pick_best_item

    store = get_store()
    excl = store.learner_seen_hashes(learner_id)
    limit = int(os.environ.get("BANK_PICK_CANDIDATES", "60"))
    candidates = store.list_ready_candidates(
        subject=subject, exclude_hashes=excl, limit=limit
    )
    if not candidates:
        return None

    try:
        ctx = build_pick_context(subject, learner_id=learner_id or "")
    except Exception as e:
        print(f"[item_bank] pick ctx failed, quality-only fallback: {e}")
        # 保底：沿用旧级联
        l1 = ""
        if kp:
            try:
                from learner.kp_registry import get_l1, syllabus_subject

                l1 = get_l1(syllabus_subject(subject), kp) or ""
            except Exception:
                l1 = ""
        return store.pick_ready_item(
            subject=subject,
            kp=kp,
            technique=technique,
            l1=l1,
            exclude_hashes=excl,
        )

    best, sc = pick_best_item(
        candidates,
        ctx,
        prefer_kp=kp or "",
        prefer_technique=technique or "",
    )
    if best:
        try:
            print(
                f"[item_bank] combined pick id={best.get('id')} kp={best.get('kp')} "
                f"score={sc:.3f} prefer_kp={kp or '-'} eta_boosts="
                f"{ {k: round(v, 3) for k, v in (ctx.domain_boosts or {}).items()} }"
            )
        except Exception:
            pass
    return best


def validate_bank_payload(
    *,
    question: str,
    techniques: list,
    solution: dict,
    cdps: list,
) -> str:
    """返回空字符串表示通过，否则错误原因。"""
    if not (question or "").strip():
        return "empty_question"
    if not techniques:
        return "no_techniques"
    steps = (solution or {}).get("steps") or []
    if not steps:
        return "no_solution_steps"
    if not isinstance(cdps, list) or len(cdps) < 2:
        return "cdps_lt_2"
    ids = set()
    for c in cdps:
        if not isinstance(c, dict) or not c.get("id"):
            return "cdp_missing_id"
        ids.add(c["id"])
        if not c.get("technique"):
            return "cdp_missing_technique"
    return ""


def structure_item_via_llm(question: str, answer: str, kp: str) -> dict[str, Any]:
    """从题干+解答抽取 techniques / solution / cdps。"""
    from decide.router import call_llm

    system = (
        "你是考研命题结构化助手。根据题目与参考解答，输出 JSON（不要其它文字）：\n"
        '{"techniques":["snake_case_tag",...],'
        '"solution":{"steps":[{"id":"s1","text":"..."}],"final_answer":"...","techniques_used":[]},'
        '"cdps":[{"id":"cdp1","prompt":"学习者此处应做什么决策",'
        '"expected":"期望选择/结论","technique":"snake_case","depends_on":[]},'
        '{"id":"cdp2",...}]}\n'
        "要求：techniques≥1；solution.steps≥2；cdps≥2 且每条带 technique。"
    )
    user = f"知识点：{kp}\n\n题目：\n{question}\n\n参考解答：\n{answer or '（无）'}"
    raw = call_llm(system, user, "author")
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def align_cdp_results(item_cdps: list, raw_results: list) -> tuple[list, bool]:
    """对齐 id；返回 (normalized, ok_aligned)。

    缺条 / 缺 ok 字段会写入占位行，但 attributable=False，不得计入学员技巧失败。
    """
    want = {str(c.get("id")): c for c in (item_cdps or []) if isinstance(c, dict) and c.get("id")}
    by_id = {}
    for r in raw_results or []:
        if isinstance(r, dict) and r.get("id"):
            by_id[str(r["id"])] = r
    out = []
    ok = True
    for cid, c in want.items():
        r = by_id.get(cid)
        if not r:
            ok = False
            out.append(
                {
                    "id": cid,
                    "ok": False,
                    "technique": c.get("technique") or "",
                    "note": "missing_from_grade",
                    "attributable": False,
                }
            )
            continue
        if "ok" not in r:
            ok = False
            out.append(
                {
                    "id": cid,
                    "ok": None,
                    "technique": str(r.get("technique") or c.get("technique") or ""),
                    "note": "missing_ok_field",
                    "attributable": False,
                }
            )
            continue
        out.append(
            {
                "id": cid,
                "ok": bool(r.get("ok")),
                "technique": str(r.get("technique") or c.get("technique") or ""),
                "note": str(r.get("note") or ""),
                "attributable": True,
            }
        )
    extras = [k for k in by_id if k not in want]
    if extras:
        ok = False
    return out, ok and len(out) == len(want)


# 对齐占位 / 模型漏填 — 不得当作学员真实技巧失败
_ALIGN_NOISE_NOTES = frozenset({"missing_from_grade", "missing_ok_field"})


def is_learner_cdp_fail(c: dict) -> bool:
    """仅学员归因失败：ok 明确为 False，且非对齐噪声。"""
    if not isinstance(c, dict):
        return False
    if c.get("ok") is not False:
        return False
    if c.get("attributable") is False:
        return False
    note = str(c.get("note") or "").strip()
    if note in _ALIGN_NOISE_NOTES:
        return False
    return True


def learner_cdp_fail_summary(cdp_results: list | None) -> dict[str, list]:
    """从 cdp_results 提取可归因失败，供 ability_snapshots / 信号汇总。"""
    fails = [c for c in (cdp_results or []) if is_learner_cdp_fail(c)]
    return {
        "technique_failures": [
            c.get("technique") for c in fails if c.get("technique")
        ],
        "cdp_fail_ids": [c.get("id") for c in fails if c.get("id")],
    }
