# -*- coding: utf-8 -*-
"""题库审判层：每日两次调度质检，劣质题压低抽题权重（防 LLM 幻觉/误判）。"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from learner.db import get_store
from quality_gate import check_draft_answer, text_contaminated


# 与推送 09/15/19、pregen 错开：上午推送前扫一轮，傍晚再扫一轮
JUDGE_SLOTS: list[str] = ["08:30", "17:30"]

POOR_SCORE = float(os.environ.get("BANK_JUDGE_POOR_SCORE", "0.12"))
MAX_PER_SLOT = int(os.environ.get("BANK_JUDGE_MAX_PER_SLOT", "3"))
MAX_REVIEWS = int(os.environ.get("BANK_JUDGE_MAX_REVIEWS", "2"))


def _machine_issues(item: dict) -> list[str]:
    """硬闸：污染词、空解答、结构空洞、CDP 不足、泄答。"""
    issues: list[str] = []
    q = (item.get("question") or "").strip()
    a = (item.get("answer") or "").strip()
    if not q:
        issues.append("empty_question")
    hits = text_contaminated(q)
    if hits and hits != ["empty"]:
        issues.append("contaminated:" + ",".join(hits[:3]))
    issues.extend(check_draft_answer(q, a, item_form=item.get("item_form") or ""))
    techs = item.get("techniques") or []
    if not techs:
        issues.append("no_techniques")
    sol = item.get("solution") or {}
    if not (sol.get("steps") or []):
        issues.append("no_solution_steps")
    cdps = item.get("cdps") or []
    if not isinstance(cdps, list) or len(cdps) < 2:
        issues.append("cdps_lt_2")
    else:
        for c in cdps:
            if not isinstance(c, dict) or not c.get("id") or not c.get("technique"):
                issues.append("cdp_incomplete")
                break
    # 题干与 KP 明显无关的极弱启发（仅作软信号，不单独判死）
    return issues


def _llm_review(item: dict) -> dict[str, Any]:
    """异模型审判（review_item）：查幻觉、答案错误、KP/技巧错标。"""
    from decide.router import call_llm

    system = (
        "你是考研题库质检官（审判层）。独立复核题目正确性，警惕出题模型幻觉与错标。\n"
        "只输出 JSON：\n"
        '{"verdict":"pass"|"fail","confidence":0.0-1.0,'
        '"reasons":["..."],'
        '"checks":{"answer_ok":true|false,"kp_match":true|false,'
        '"cdp_coherent":true|false,"solution_ok":true|false}}\n'
        "fail 条件：答案错误/推导断裂/KP 与题干不符/CDP 与技巧胡扯/明显超纲胡编。"
    )
    payload = {
        "kp": item.get("kp"),
        "techniques": item.get("techniques"),
        "question": (item.get("question") or "")[:4000],
        "answer": (item.get("answer") or "")[:3000],
        "solution": item.get("solution") or {},
        "cdps": item.get("cdps") or [],
    }
    user = "待审题目：\n" + json.dumps(payload, ensure_ascii=False)
    raw = call_llm(system, user, "review_item")
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {"verdict": "fail", "confidence": 0.3, "reasons": ["llm_unparseable"], "raw": raw}
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return {"verdict": "fail", "confidence": 0.3, "reasons": ["llm_bad_json"], "raw": raw}
    if not isinstance(data, dict):
        return {"verdict": "fail", "confidence": 0.3, "reasons": ["llm_not_obj"]}
    verdict = str(data.get("verdict") or "").lower()
    if verdict not in ("pass", "fail"):
        # 任一关键 checks 为 false → fail
        checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
        if checks and any(checks.get(k) is False for k in checks):
            verdict = "fail"
        else:
            verdict = "fail"
            data.setdefault("reasons", []).append("missing_verdict")
    return {
        "verdict": verdict,
        "confidence": float(data.get("confidence") or 0.5),
        "reasons": list(data.get("reasons") or []),
        "checks": data.get("checks") or {},
    }


def judge_one_item(item: dict, *, use_llm: bool = True) -> dict[str, Any]:
    """单题审判：机器硬闸 →（可选）异模型 LLM。"""
    store = get_store()
    iid = int(item["id"])
    machine = _machine_issues(item)
    if machine:
        applied = store.apply_judge_verdict(
            iid,
            verdict="fail",
            reasons=machine,
            confidence=1.0,
            details={"phase": "machine"},
            poor_score=POOR_SCORE,
        )
        return {"ok": True, **applied, "phase": "machine"}

    if not use_llm:
        applied = store.apply_judge_verdict(
            iid,
            verdict="pass",
            reasons=["machine_only_pass"],
            confidence=0.6,
            details={"phase": "machine_only"},
            poor_score=POOR_SCORE,
        )
        return {"ok": True, **applied, "phase": "machine_only"}

    try:
        llm = _llm_review(item)
    except Exception as e:
        # 审判通道失败：保持 pending，不标 poor（避免通道故障误伤）
        def _note(conn):
            row = conn.execute(
                "SELECT judge_meta, judge_count FROM items WHERE id=?", (iid,)
            ).fetchone()
            meta = {}
            try:
                meta = json.loads((row["judge_meta"] if row else None) or "{}")
            except (TypeError, json.JSONDecodeError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            reviews = list(meta.get("reviews") or [])
            from learner.db import now_utc_iso

            reviews.append(
                {
                    "at": now_utc_iso(),
                    "verdict": "error",
                    "reasons": [f"llm_error:{e}"],
                    "confidence": 0.0,
                    "details": {"phase": "llm_error"},
                }
            )
            meta["reviews"] = reviews[-8:]
            # 不增加 judge_count，下个槽可重试
            conn.execute(
                "UPDATE items SET judge_meta=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), iid),
            )
            return True

        store._txn(_note)
        return {
            "ok": False,
            "item_id": iid,
            "phase": "llm_error",
            "error": str(e),
            "quality_tier": "pending",
        }

    # 低置信度 fail 仍标 poor；低置信度 pass 保持 pending 语义上仍写 pass 但 score 略降
    verdict = llm["verdict"]
    conf = float(llm.get("confidence") or 0.5)
    score_override = None
    if verdict == "pass" and conf < 0.55:
        # 犹豫通过：可再审（不占满 pass），用中间分
        applied = store.apply_judge_verdict(
            iid,
            verdict="pass",
            reasons=list(llm.get("reasons") or []) + ["low_confidence_pass"],
            confidence=conf,
            details={"phase": "llm", "checks": llm.get("checks")},
            poor_score=POOR_SCORE,
        )
        # 覆写成中等分，仍可被第二次审判（judge_count 已+1；若 < MAX 仍可进队需 quality_tier pending）
        # 低置信通过 → 改回 pending 以便第二次槽再审
        def _soft(conn):
            conn.execute(
                """UPDATE items SET quality_tier='pending', quality_score=? WHERE id=?""",
                (0.7, iid),
            )
            return True

        store._txn(_soft)
        applied["quality_tier"] = "pending"
        applied["quality_score"] = 0.7
        return {"ok": True, **applied, "phase": "llm_soft_pass", "llm": llm}

    applied = store.apply_judge_verdict(
        iid,
        verdict=verdict,
        reasons=list(llm.get("reasons") or []),
        confidence=conf,
        details={"phase": "llm", "checks": llm.get("checks")},
        poor_score=POOR_SCORE,
    )
    return {"ok": True, **applied, "phase": "llm", "llm": llm}


def run_judge_slot(*, max_items: int | None = None, use_llm: bool = True) -> dict[str, Any]:
    """调度入口：每槽最多审 N 道；每题最多 MAX_REVIEWS 次。"""
    limit = int(max_items if max_items is not None else MAX_PER_SLOT)
    if limit < 1:
        return {"ok": False, "error": "max_items_lt_1"}

    store = get_store()
    items = store.list_items_for_judge(max_reviews=MAX_REVIEWS, limit=limit)
    if not items:
        return {"ok": True, "skipped": True, "reason": "nothing_to_judge", "reviewed": []}

    reviewed = []
    for it in items:
        try:
            r = judge_one_item(it, use_llm=use_llm)
        except Exception as e:
            r = {"ok": False, "item_id": it.get("id"), "error": str(e)}
        reviewed.append(r)
    return {
        "ok": True,
        "skipped": False,
        "count": len(reviewed),
        "reviewed": reviewed,
    }
