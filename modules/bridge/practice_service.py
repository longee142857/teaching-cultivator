"""Practice desk service — bootstrap / item / submit for teaching-shell.

Grading modes (env ``PRACTICE_GRADE_MODE``):
- ``llm`` (default): call ``grade.grade_answer`` (writes BKT + attempt)
- ``ref``: compare to item.answer / solution.final_answer (offline / CI)

Tutor chat is intentionally stubbed (``tutor_enabled=False``).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional

from modules.bridge.practice_dto import (
    SLOT_SPECS,
    build_slots,
    empty_slots,
    explain_from_solution,
    normalize_answer_text,
    parse_item_id,
    parse_push_id,
    push_to_shell_item,
)


def grade_mode() -> str:
    return (os.environ.get("PRACTICE_GRADE_MODE") or "llm").strip().lower()


def allow_demo_seed() -> bool:
    return os.environ.get("PRACTICE_ALLOW_DEMO_SEED", "0") == "1"


def _simpletex_ready() -> bool:
    try:
        from deliver.simpletex import is_configured

        return bool(is_configured())
    except Exception:
        return False


def _decode_ocr_image(raw: str) -> bytes:
    import base64

    s = (raw or "").strip()
    if not s:
        return b""
    if s.startswith("data:"):
        _, _, s = s.partition(",")
    try:
        return base64.b64decode(s, validate=False)
    except Exception:
        return b""


def practice_ocr(
    image: str = "",
    filename: str = "",
    mode: str = "",
) -> dict[str, Any]:
    """POST /api/v1/practice/ocr — existing SimpleTex client, no new OCR product."""
    data = _decode_ocr_image(image)
    if not data:
        return {"ok": False, "error": "empty_image", "text": ""}
    if len(data) > 3_500_000:
        return {"ok": False, "error": "image_too_large", "text": ""}
    if not _simpletex_ready():
        return {"ok": False, "error": "simpletex_not_configured", "text": ""}
    use_mode = (mode or "").strip().lower()
    if use_mode in ("document", "page", "general", ""):
        use_mode = "general"
    elif use_mode in ("formula", "latex", "formula_std"):
        use_mode = "formula"
    from deliver.simpletex import ocr_image

    return ocr_image(data, filename=(filename or "answer.jpg").strip() or "answer.jpg", mode=use_mode)


def tutor_status() -> dict[str, Any]:
    backend = (os.environ.get("TUTOR_BACKEND_URL") or "").strip().rstrip("/")
    if backend:
        return {
            "enabled": True,
            "reason": "proxied",
            "backend": backend,
            "hint": "POST /api/v1/tutor/chat proxies to TUTOR_BACKEND_URL (DSH mentor-team)",
        }
    return {
        "enabled": False,
        "reason": "tutor_agent_not_wired",
        "hint": "Set TUTOR_BACKEND_URL to attach DSH mentor-team; else 501",
    }


def agent_manifest() -> dict[str, Any]:
    """Stable surface for practice desk + optional DSH tutor proxy."""
    wired = bool((os.environ.get("TUTOR_BACKEND_URL") or "").strip())
    return {
        "service": "teaching-practice",
        "version": 1,
        "practice": {
            "bootstrap": {"method": "GET", "path": "/api/v1/practice/bootstrap"},
            "item": {"method": "GET", "path": "/api/v1/practice/item"},
            "submit": {"method": "POST", "path": "/api/v1/practice/submit"},
            "ocr": {
                "method": "POST",
                "path": "/api/v1/practice/ocr",
                "status": "simpletex" if _simpletex_ready() else "stub_501",
                "backend": "deliver.simpletex",
            },
            "params": {"method": "GET", "path": "/api/v1/practice/params"},
        },
        "tutor": {
            "chat": {
                "method": "POST",
                "path": "/api/v1/tutor/chat",
                "status": "proxied" if wired else "stub_501",
                "backend": "TUTOR_BACKEND_URL" if wired else None,
                "request": {
                    "learner": "str",
                    "item": "str|null",
                    "push": "str|null",
                    "message": "str",
                    "threadId": "str|null",
                    "mentor": "str?",
                },
                "response": {
                    "reply": "str",
                    "streaming": "bool?",
                    "citations": "list?",
                },
            }
        },
        "capability": {
            "events": {
                "list": {"method": "GET", "path": "/api/v1/capability/events"},
                "upsert": {
                    "method": "POST",
                    "path": "/api/v1/capability/events",
                    "note": "mentor-writable event catalog for Brain",
                },
            }
        },
        "system_api_tools": [
            "practice_bootstrap",
            "practice_get_item",
            "practice_submit",
            "get_learner_params",
            "get_capability_evidence",
        ],
        "deeplink": {
            "path": "/practice",
            "query": ["learner", "item", "push", "mode", "view"],
        },
        "notes": [
            "IM notify only; answers go through practice submit",
            "item public id is i{n}; push is integer push id",
            "tutor chat: set TUTOR_BACKEND_URL → proxy to integrations/dsh-mentor-team; else 501",
            "DSH mentor-team is read-only for grade/generate; may write capability events",
        ],
    }


def _today() -> str:
    from learner.db import TZ_SHANGHAI

    return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")


def _store():
    from modules.store import get_store

    return get_store()


def _iter_mastery(mastery: Any) -> list[tuple[str, float]]:
    """LearnerParams.to_dict() uses a list; older snapshots may still be a dict."""
    out: list[tuple[str, float]] = []
    if isinstance(mastery, dict):
        for k, v in mastery.items():
            kp = str(k or "").strip()
            if not kp or kp == "未分类":
                continue
            try:
                if isinstance(v, dict):
                    p = float(v.get("p_mastery") or v.get("p") or 0)
                else:
                    p = float(v)
            except (TypeError, ValueError):
                continue
            out.append((kp, p))
        return out
    if isinstance(mastery, (list, tuple)):
        for entry in mastery:
            if not isinstance(entry, dict):
                continue
            kp = str(entry.get("kp") or entry.get("knowledge_point") or "").strip()
            if not kp or kp == "未分类":
                continue
            try:
                p = float(entry.get("p_mastery") or entry.get("p") or 0)
            except (TypeError, ValueError):
                continue
            out.append((kp, p))
    return out


def _eta_map(eta: Any) -> dict[str, Any]:
    if isinstance(eta, dict):
        out: dict[str, Any] = {}
        for k, v in eta.items():
            if isinstance(v, dict) and "eta" in v:
                out[str(k)] = v.get("eta")
            else:
                out[str(k)] = v
        return out
    if isinstance(eta, (list, tuple)):
        out = {}
        for e in eta:
            if isinstance(e, dict) and e.get("domain") is not None:
                out[str(e["domain"])] = e.get("eta")
        return out
    return {}


def _weak_hint(learner_id: str, params: dict | None = None) -> str:
    try:
        if params is None:
            from modules.bridge import LearnerBridge

            params = LearnerBridge(store=_store()).get_learner_params(learner_id)
        weak = [(p, kp) for kp, p in _iter_mastery(params.get("mastery")) if p < 0.45]
        weak.sort()
        if weak:
            return f"近期易错：{weak[0][1]}"
        signals = params.get("signals") or params.get("ability_signals") or {}
        if isinstance(signals, dict) and signals.get("prefer_kp"):
            return f"建议优先：{signals['prefer_kp']}"
    except Exception:
        pass
    return "建议优先完成今日最早未答槽"


def _params_summary(learner_id: str) -> dict[str, Any]:
    try:
        from modules.bridge import LearnerBridge

        full = LearnerBridge(store=_store()).get_learner_params(learner_id)
        eta = _eta_map(full.get("eta") or full.get("domain_eta"))
        top = sorted(_iter_mastery(full.get("mastery")), key=lambda x: x[1])[:5]
        return {
            "eta": eta,
            "masteryWeak": [{"kp": k, "p": round(p, 3)} for k, p in top],
            "assumptions": full.get("assumptions") or {},
        }
    except Exception:
        return {"eta": {}, "masteryWeak": []}


def _attempt_result_dto(attempt: dict | None, item_dto: dict) -> Optional[dict[str, Any]]:
    if not attempt:
        return None
    correct = attempt.get("correct")
    submitted = ""
    meta = attempt
    if isinstance(attempt.get("meta"), dict):
        meta = attempt["meta"]
    submitted = (
        meta.get("user_answer")
        or meta.get("submitted")
        or meta.get("answer")
        or ""
    )
    feedback = meta.get("feedback") or meta.get("comment") or ""
    if not feedback:
        feedback = item_dto["commentOk"] if correct else item_dto["commentBad"]
    return {
        "correct": bool(correct) if correct is not None else False,
        "comment": feedback,
        "explain": item_dto.get("explain") or "",
        "submitted": submitted,
        "status": attempt.get("status") or meta.get("status") or "applied",
        "credit": attempt.get("credit"),
        "kp": attempt.get("knowledge_point") or item_dto.get("kp"),
    }


def ensure_demo_seed(learner_id: str, *, store=None) -> bool:
    """Insert three demo pushes for today when empty (opt-in)."""
    if not allow_demo_seed():
        return False
    store = store or _store()
    day = _today()
    existing = store.list_today_pushes(learner_id, day)
    if existing:
        return False
    demos = [
        (
            "math",
            "极限 · 夹逼定理",
            "求极限\n\n已知数列满足不等式约束，求极限。\n\n$$\\lim_{n\\to\\infty} a_n = ?\\quad "
            "(\\tfrac{1}{n} \\le a_n \\le \\tfrac{n+1}{n^2})$$",
            "0",
            {
                "steps": [
                    {"id": "s1", "text": "由 1/n ≤ a_n ≤ (n+1)/n²"},
                    {"id": "s2", "text": "两端当 n→∞ 时均趋于 0，故 a_n → 0"},
                ],
                "final_answer": "0",
            },
        ),
        (
            "comm",
            "信号与系统 · 卷积",
            "系统输出\n\n已知输入与冲激响应，求输出信号的表达式要点。\n\n"
            "$$y(t) = x(t) * h(t) = \\int_{-\\infty}^{\\infty} x(\\tau)h(t-\\tau)\\,d\\tau$$",
            "卷积",
            {
                "steps": [
                    {"id": "s1", "text": "输出为输入与冲激响应的卷积"},
                    {"id": "s2", "text": "先画支撑再定积分限"},
                ],
                "final_answer": "y(t)=x*h",
            },
        ),
        (
            "review",
            "导数 · 隐函数求导",
            "隐函数求导（复习）\n\n由方程 F(x,y)=0 确定 y=y(x)，求 dy/dx。\n\n"
            "$$x^2 + xy + y^2 = 3,\\quad \\left.\\dfrac{dy}{dx}\\right|_{(1,1)}$$",
            "-1",
            {
                "steps": [
                    {"id": "s1", "text": "两边对 x 求导得 y' = −(2x+y)/(x+2y)"},
                    {"id": "s2", "text": "点 (1,1) 处为 −1"},
                ],
                "final_answer": "-1",
            },
        ),
    ]
    for subject, kp, question, answer, solution in demos:
        item_id = store.insert_bank_item(
            subject=subject,
            question=question,
            answer=answer,
            difficulty="intermediate",
            kp=kp,
            solution=solution,
            status="ready",
            meta={"demo": True, "source": "practice_seed"},
        )
        store.record_push_for_item(
            item_id=item_id,
            learner_id=learner_id,
            slot=subject,
            decision_type="push",
            reason=f"demo:{kp}",
        )
    # one backlog item (yesterday wall-clock → Shanghai day)
    from learner.db import TZ_SHANGHAI, utc_from_shanghai

    yday = (datetime.now(TZ_SHANGHAI) - timedelta(days=1)).strftime("%Y-%m-%d")
    bid = store.insert_bank_item(
        subject="math",
        question="定积分（历史未答）\n\n$$\\displaystyle\\int_0^{1} \\dfrac{x}{\\sqrt{1+x^2}}\\,dx$$",
        answer="√2-1",
        kp="积分 · 换元",
        solution={
            "steps": [{"id": "s1", "text": "令 u=1+x²，积分化为 √2 − 1"}],
            "final_answer": "√2-1",
        },
        status="ready",
        meta={"demo": True},
    )
    store.record_push_for_item(
        item_id=bid,
        learner_id=learner_id,
        slot="math",
        decision_type="push",
        reason="demo:backlog",
        pushed_at=utc_from_shanghai(yday, "10:00"),
    )
    return True


def _bank_item_as_row(item: dict, *, day: str, kind: str) -> dict[str, Any]:
    return {
        "push_id": None,
        "item_id": int(item.get("id") or 0),
        "question": item.get("question"),
        "answer": item.get("answer"),
        "subject": item.get("subject") or item.get("bank_subject") or kind,
        "kp": item.get("kp"),
        "solution": item.get("solution") or {},
        "difficulty": item.get("difficulty"),
        "slot": kind,
        "day": day,
        "answered": False,
        "from_bank": True,
    }


def _pick_ready_for_kind(
    kind: str,
    learner_id: str,
    *,
    store,
    exclude_ids: set[int],
) -> dict | None:
    """Fill an empty desk slot from the ready bank (no new service / no write)."""
    subject = (kind or "").strip() or "math"
    excl_hashes: set[str] = set()
    if hasattr(store, "learner_seen_hashes"):
        try:
            excl_hashes = store.learner_seen_hashes(learner_id) or set()
        except Exception:
            excl_hashes = set()

    def _accept(it: dict | None) -> dict | None:
        if not it:
            return None
        try:
            iid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            return None
        if not iid or iid in exclude_ids:
            return None
        return it

    try:
        from learner.item_bank import pick_for_push

        hit = _accept(pick_for_push(subject, learner_id=learner_id or None))
        if hit:
            return hit
    except Exception:
        pass
    if hasattr(store, "pick_ready_item"):
        hit = _accept(store.pick_ready_item(subject=subject, exclude_hashes=excl_hashes))
        if hit:
            return hit
    if hasattr(store, "list_ready_candidates"):
        try:
            for cand in store.list_ready_candidates(
                subject=subject, exclude_hashes=excl_hashes, limit=20
            ):
                hit = _accept(cand)
                if hit:
                    return hit
        except Exception:
            pass
    return None


def bootstrap(learner_id: str, *, day: str | None = None, store=None) -> dict[str, Any]:
    lid = (learner_id or "").strip()
    if not lid:
        return {"ok": False, "error": "missing learner"}
    store = store or _store()
    ensure_demo_seed(lid, store=store)
    day = day or _today()
    today_rows = store.list_today_pushes(lid, day)
    recent = store.list_recent_pushes(lid, days=7)

    by_kind: dict[str, dict] = {}
    items: list[dict] = []
    seen: set[str] = set()
    answered_map: dict[str, Any] = {}

    def _add(row: dict, *, backlog: bool) -> dict:
        dto = push_to_shell_item(row, backlog=backlog)
        pid = dto["id"]
        if pid in seen:
            return dto
        seen.add(pid)
        items.append(dto)
        if dto.get("answered") and dto.get("pushId"):
            att = store.get_attempt_for_push(int(dto["pushId"]))
            # filter by user
            if att and (att.get("user_id") or "") == lid:
                r = _attempt_result_dto(att, dto)
                if r:
                    answered_map[pid] = r
        return dto

    for row in today_rows:
        dto = _add(row, backlog=False)
        kind = dto["kind"]
        if kind not in by_kind:
            by_kind[kind] = dto
        elif not by_kind[kind].get("answered") and dto.get("answered"):
            pass
        elif by_kind[kind].get("answered") and not dto.get("answered"):
            by_kind[kind] = dto

    for row in recent:
        if (row.get("day") or "") >= day:
            continue
        # unanswered backlog only
        if store._push_answered(int(row["push_id"]), lid):
            continue
        _add(row, backlog=True)

    used_ids = {int(i.get("itemId") or 0) for i in items if i.get("itemId")}
    filled_from_bank = False
    for spec in SLOT_SPECS:
        kind = spec["kind"]
        if kind in by_kind:
            continue
        bank_item = _pick_ready_for_kind(kind, lid, store=store, exclude_ids=used_ids)
        if not bank_item:
            continue
        dto = _add(_bank_item_as_row(bank_item, day=day, kind=kind), backlog=False)
        dto["fromBank"] = True
        by_kind[kind] = dto
        try:
            used_ids.add(int(dto.get("itemId") or 0))
        except (TypeError, ValueError):
            pass
        filled_from_bank = True

    slots = build_slots(by_kind) if by_kind else empty_slots()
    # if today had pushes but kinds missing, still keep empty slot stubs
    if today_rows and not by_kind:
        slots = empty_slots()

    params = _params_summary(lid)
    hint = _weak_hint(lid)
    if filled_from_bank and not today_rows:
        extra = "今日暂无排程推送，已从 ready 题库补入可练题目。"
        hint = extra if hint.startswith("建议优先") else f"{extra} {hint}"

    return {
        "ok": True,
        "learner": lid,
        "day": day,
        "slots": slots,
        "items": items,
        "answered": answered_map,
        "weakHint": hint,
        "capability": params,
        "tutor": tutor_status(),
        "gradeMode": grade_mode(),
        "emptyDay": bool(not today_rows),
        "fromBank": filled_from_bank,
        "stats": {
            "cached": len(SLOT_SPECS),
            "today": len([i for i in items if not i.get("backlog")]),
            "remaining": len(
                [i for i in items if not i.get("backlog") and not answered_map.get(i["id"])]
            ),
            "done": len(
                [i for i in items if not i.get("backlog") and answered_map.get(i["id"])]
            ),
            "fromBank": filled_from_bank,
        },
    }


def get_item(
    learner_id: str,
    *,
    item: str | int | None = None,
    push: str | int | None = None,
    kind: str | None = None,
    store=None,
) -> dict[str, Any]:
    lid = (learner_id or "").strip()
    if not lid:
        return {"ok": False, "error": "missing learner"}
    store = store or _store()
    push_id = parse_push_id(push)
    item_id = parse_item_id(item)
    slot_kind = (kind or "").strip().lower()
    row = None
    from_bank = False
    if push_id is not None:
        row = store.get_push(push_id)
    if row is None and item_id is not None:
        # latest push for this item visible to learner
        recent = store.list_recent_pushes(lid, days=30)
        for r in recent:
            if int(r.get("item_id") or 0) == item_id:
                row = r
                break
        if row is None:
            it = store.get_item(item_id)
            if it:
                row = {
                    "push_id": None,
                    "item_id": item_id,
                    "learner_id": lid,
                    "day": _today(),
                    "question": it.get("question"),
                    "answer": it.get("answer"),
                    "subject": it.get("subject"),
                    "kp": it.get("kp"),
                    "solution": it.get("solution"),
                    "difficulty": it.get("difficulty"),
                    "slot": it.get("subject") or "",
                    "answered": False,
                }
    if row is None and slot_kind:
        bank = _pick_ready_for_kind(slot_kind, lid, store=store, exclude_ids=set())
        if bank:
            row = _bank_item_as_row(bank, day=_today(), kind=slot_kind)
            from_bank = True
    if row is None:
        return {"ok": False, "error": "item_not_found"}
    day = _today()
    backlog = bool(row.get("day") and row["day"] < day)
    if row.get("push_id") is not None:
        row = dict(row)
        row["answered"] = store._push_answered(int(row["push_id"]), lid)
    dto = push_to_shell_item(row, backlog=backlog)
    if from_bank or row.get("from_bank"):
        dto["fromBank"] = True
    result = None
    if dto.get("answered") and dto.get("pushId"):
        att = store.get_attempt_for_push(int(dto["pushId"]))
        if att and (att.get("user_id") or "") == lid:
            result = _attempt_result_dto(att, dto)
    return {"ok": True, "item": dto, "result": result, "tutor": tutor_status()}


def _ref_grade(item_row: dict, user_answer: str) -> tuple[bool, float | None, str]:
    ua = normalize_answer_text(user_answer)
    if not ua or ua in ("错", "不知道", "不会"):
        return False, None, "未给出有效解答。"
    candidates: list[str] = []
    ans = (item_row.get("answer") or "").strip()
    if ans:
        candidates.append(ans)
    sol = item_row.get("solution") or {}
    if isinstance(sol, dict):
        fa = (sol.get("final_answer") or "").strip()
        if fa:
            candidates.append(fa)
    for c in candidates:
        nc = normalize_answer_text(c)
        if not nc:
            continue
        if ua == nc or nc in ua or ua in nc:
            return True, None, "与参考答案一致（ref 模式）。"
    # soft numeric / keyword
    if any(normalize_answer_text(c) and normalize_answer_text(c) in ua for c in candidates):
        return True, None, "命中参考要点（ref 模式）。"
    return False, None, "与参考答案不一致（ref 模式）。"


def _coerce_row_id(v) -> int | None:
    n = parse_item_id(v)
    if n is None:
        n = parse_push_id(v)
    return n if n and n > 0 else None


def _resolve_submit_ids(row: dict, dto: dict, store) -> tuple[int | None, int | None]:
    """Prefer desk DTO, then row, then question-hash item (empty-day / fromBank)."""
    push_id = _coerce_row_id(dto.get("pushId") if dto else None) or _coerce_row_id(
        row.get("push_id")
    )
    item_id = _coerce_row_id(dto.get("itemId") if dto else None) or _coerce_row_id(
        row.get("item_id")
    )
    if item_id is None:
        q = (row.get("question") or "").strip()
        subj = (row.get("subject") or "").strip()
        if q and hasattr(store, "get_item_by_question"):
            try:
                it = store.get_item_by_question(q, subj)
            except Exception:
                it = None
            if it:
                item_id = _coerce_row_id(it.get("id") or it.get("item_id"))
    return push_id, item_id


def _attempt_linked(store, learner_id: str, *, push_id, item_id) -> bool:
    lid = (learner_id or "").strip()
    if push_id:
        try:
            att = store.get_attempt_for_push(int(push_id))
        except Exception:
            att = None
        if att and (att.get("user_id") or "") == lid:
            return True
    if item_id and hasattr(store, "get_attempts"):
        try:
            want = int(item_id)
        except (TypeError, ValueError):
            return False
        for a in store.get_attempts(lid):
            try:
                if int(a.get("item_id") or 0) == want:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _record_ref_attempt(
    *,
    learner_id: str,
    push_id: int | None,
    item_id: int | None,
    kp: str,
    subject: str,
    correct: bool,
    credit: float | None,
    feedback: str,
    user_answer: str,
    store,
) -> int:
    from modules.store import now_utc_iso

    entry = {
        "ts": now_utc_iso(),
        "user_id": learner_id,
        "push_id": push_id,
        "item_id": item_id,
        "knowledge_point": kp or "未分类",
        "correct": correct,
        "credit": credit,
        "item_type": "practice",
        "status": "applied",
        "confidence": 1.0,
        "feedback": feedback,
        "user_answer": user_answer,
        "subject": subject,
        "update_applied": False,
        "update_reason": "practice_ref_grade",
    }
    aid = store.add_attempt_entry(entry)
    try:
        from modules.capability import refresh_after_grade

        refresh_after_grade(learner_id, store=store, persist_snapshot=True)
    except Exception:
        pass
    return aid


def submit(
    learner_id: str,
    *,
    answer: str,
    item: str | int | None = None,
    push: str | int | None = None,
    store=None,
    mode: str | None = None,
) -> dict[str, Any]:
    lid = (learner_id or "").strip()
    ua = (answer or "").strip()
    if not lid:
        return {"ok": False, "error": "missing learner"}
    if not ua:
        return {"ok": False, "error": "empty_answer"}
    store = store or _store()
    mode = (mode or grade_mode()).strip().lower()

    got = get_item(lid, item=item, push=push, store=store)
    if not got.get("ok"):
        return got
    dto = got["item"]
    push_id = _coerce_row_id(dto.get("pushId"))
    item_id = _coerce_row_id(dto.get("itemId"))
    # load authoritative row for question/answer
    row = store.get_push(int(push_id)) if push_id else None
    if row is None and item_id:
        it = store.get_item(int(item_id))
        if not it:
            return {"ok": False, "error": "item_not_found"}
        row = {
            "question": it.get("question"),
            "answer": it.get("answer"),
            "kp": it.get("kp"),
            "subject": it.get("subject"),
            "solution": it.get("solution"),
            "item_id": item_id,
            "push_id": push_id,
        }

    question = (row.get("question") or "").strip()
    kp = (row.get("kp") or dto.get("kp") or "").strip()
    subject = (row.get("subject") or "").strip()
    explain = dto.get("explain") or explain_from_solution(row.get("solution") or {})
    push_id, item_id = _resolve_submit_ids(row, dto, store)

    used_mode = mode
    result_dto: dict[str, Any]

    from learner.context import bind_learner

    with bind_learner(lid, binding="personal"):
        if mode == "llm":
            try:
                from grade import grade_answer as _grade

                try:
                    gr = _grade(
                        question,
                        ua,
                        kp_name=kp,
                        subject=subject,
                        item_id=item_id,
                        push_id=push_id,
                    )
                except TypeError:
                    gr = _grade(question, ua, kp_name=kp, subject=subject)
                correct = bool(gr.is_correct) if gr.credit is None else False
                if gr.credit is not None:
                    # partial → treat as not fully correct for shell boolean
                    correct = False
                comment = gr.feedback or (
                    dto["commentOk"] if gr.is_correct else dto["commentBad"]
                )
                if gr.credit is not None:
                    comment = f"部分正确。{comment}"
                result_dto = {
                    "correct": bool(gr.is_correct) and gr.credit is None,
                    "partial": gr.credit is not None,
                    "comment": comment,
                    "explain": explain,
                    "submitted": ua,
                    "status": gr.status,
                    "credit": gr.credit,
                    "confidence": gr.confidence,
                    "kp": gr.kp_name or kp,
                    "masteryBefore": round(gr.p_mastery_before, 4),
                    "masteryAfter": round(gr.p_mastery_after, 4),
                    "gradeMode": "llm",
                }
                # grade_answer writes BKT+attempt; if it missed (no push / 未分类 /
                # BKT exception) still persist item_id for empty-day / fromBank.
                if not _attempt_linked(store, lid, push_id=push_id, item_id=item_id):
                    store.add_attempt_entry(
                        {
                            "user_id": lid,
                            "push_id": push_id,
                            "item_id": item_id,
                            "knowledge_point": result_dto["kp"],
                            "correct": result_dto["correct"],
                            "credit": gr.credit,
                            "item_type": gr.item_type,
                            "status": gr.status,
                            "confidence": gr.confidence,
                            "feedback": comment,
                            "user_answer": ua,
                        }
                    )
            except Exception as e:
                used_mode = "ref_fallback"
                correct, credit, feedback = _ref_grade(row, ua)
                _record_ref_attempt(
                    learner_id=lid,
                    push_id=push_id,
                    item_id=item_id,
                    kp=kp,
                    subject=subject,
                    correct=correct,
                    credit=credit,
                    feedback=f"{feedback}（LLM 不可用：{e}）",
                    user_answer=ua,
                    store=store,
                )
                result_dto = {
                    "correct": correct,
                    "partial": False,
                    "comment": feedback if correct else dto["commentBad"],
                    "explain": explain,
                    "submitted": ua,
                    "status": "applied",
                    "credit": credit,
                    "kp": kp,
                    "gradeMode": used_mode,
                    "warning": f"llm_failed:{e}",
                }
        else:
            correct, credit, feedback = _ref_grade(row, ua)
            _record_ref_attempt(
                learner_id=lid,
                push_id=push_id,
                item_id=item_id,
                kp=kp,
                subject=subject,
                correct=correct,
                credit=credit,
                feedback=feedback,
                user_answer=ua,
                store=store,
            )
            result_dto = {
                "correct": correct,
                "partial": False,
                "comment": feedback if correct else (dto["commentBad"] + " " + feedback),
                "explain": explain,
                "submitted": ua,
                "status": "applied",
                "credit": credit,
                "kp": kp,
                "gradeMode": "ref",
            }

    return {
        "ok": True,
        "item": dto,
        "result": result_dto,
        "capability": _params_summary(lid),
        "tutor": tutor_status(),
    }


def get_params(learner_id: str) -> dict[str, Any]:
    lid = (learner_id or "").strip()
    if not lid:
        return {"ok": False, "error": "missing learner"}
    try:
        from modules.bridge import LearnerBridge

        full = LearnerBridge().get_learner_params(lid)
        return {"ok": True, "learner": lid, "params": full, "summary": _params_summary(lid)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── system_api tool wrappers (string learner via X-Learner-Id context) ──


def practice_bootstrap(user_id: str = "", day: str = "") -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        from learner.context import current_user_id

        uid = current_user_id()
    return bootstrap(uid, day=day or None)


def practice_get_item(user_id: str = "", item: str = "", push: str = "", kind: str = "") -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        from learner.context import current_user_id

        uid = current_user_id()
    return get_item(uid, item=item or None, push=push or None, kind=kind or None)


def practice_submit(
    user_id: str = "",
    answer: str = "",
    item: str = "",
    push: str = "",
    mode: str = "",
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        from learner.context import current_user_id

        uid = current_user_id()
    return submit(
        uid,
        answer=answer,
        item=item or None,
        push=push or None,
        mode=mode or None,
    )


__all__ = [
    "agent_manifest",
    "bootstrap",
    "ensure_demo_seed",
    "get_item",
    "get_params",
    "grade_mode",
    "practice_bootstrap",
    "practice_get_item",
    "practice_ocr",
    "practice_submit",
    "submit",
    "tutor_status",
]
