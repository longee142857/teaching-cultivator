# -*- coding: utf-8 -*-
"""推进模式：learning_mode 与书序 cursor。进度只写 teaching.db。"""
from __future__ import annotations

import os
from typing import Any

from learner.atom_book import (
    BOOK_FAN,
    BOOK_ZHOU,
    L3_MIN_CONF,
    best_l3,
    book_accepted,
    core_spans,
    first_atom_id,
    get_atom,
    list_atoms_in_book_order,
    next_atom_after,
    schema_ok,
)
from learner.db import get_store, now_utc_iso

ESCAPE_K = int(os.environ.get("ADVANCE_ESCAPE_K", "5"))


def _owner_id() -> str:
    try:
        from learner.context import owner_staff_id, current_user_id

        return (owner_staff_id() or current_user_id() or "").strip()
    except Exception:
        return ""


def get_learning_mode(subject: str = "comm", learner_id: str = "") -> dict[str, str]:
    lid = (learner_id or "").strip() or _owner_id()
    subj = (subject or "comm").strip().lower()
    if not lid:
        return {"learning_mode": "free", "book_id": BOOK_ZHOU, "learner_id": ""}
    row = get_store().get_learner_mode(lid, subj)
    if not row:
        return {
            "learning_mode": "free",
            "book_id": BOOK_ZHOU,
            "learner_id": lid,
        }
    return row


def set_learning_mode(
    subject: str = "comm",
    mode: str = "free",
    book: str = BOOK_ZHOU,
    learner_id: str = "",
) -> dict[str, Any]:
    mode = (mode or "free").strip().lower()
    book = (book or BOOK_ZHOU).strip() or BOOK_ZHOU
    subj = (subject or "comm").strip().lower()
    if mode not in ("free", "advance"):
        return {"ok": False, "error": "bad_mode"}
    if subj != "comm":
        return {"ok": False, "error": "advance_only_comm"}
    if book not in (BOOK_ZHOU, BOOK_FAN):
        return {"ok": False, "error": "bad_book"}
    if mode == "advance":
        if not book_accepted(book):
            ok, why = schema_ok(book)
            return {
                "ok": False,
                "error": "book_not_accepted",
                "schema_ok": ok,
                "reason": why,
                "hint": "原子库未验收，禁止打开 advance",
            }
    lid = (learner_id or "").strip() or _owner_id()
    if not lid:
        return {"ok": False, "error": "no_learner"}
    get_store().set_learner_mode(lid, subj, mode, book)
    out: dict[str, Any] = {
        "ok": True,
        "learner_id": lid,
        "subject": subj,
        "learning_mode": mode,
        "book_id": book,
    }
    if mode == "advance" and os.environ.get("ADVANCE_FILL_ON_ENABLE", "1").strip() != "0":
        try:
            out["reserved"] = ensure_reserved_comm_item(lid)
        except Exception as e:
            out["reserved_error"] = f"{type(e).__name__}:{e}"
    return out


def advance_active(subject: str = "comm", learner_id: str = "") -> bool:
    if (subject or "").strip().lower() != "comm":
        return False
    row = get_learning_mode("comm", learner_id)
    if (row.get("learning_mode") or "") != "advance":
        return False
    book = row.get("book_id") or BOOK_ZHOU
    return book_accepted(book)


def current_book_id(learner_id: str = "") -> str:
    row = get_learning_mode("comm", learner_id)
    return (row.get("book_id") or BOOK_ZHOU).strip() or BOOK_ZHOU


def get_cursor(learner_id: str = "", book_id: str = "") -> dict[str, Any] | None:
    lid = (learner_id or "").strip() or _owner_id()
    book = (book_id or current_book_id(lid)).strip() or BOOK_ZHOU
    if not lid:
        return None
    return get_store().get_book_cursor(lid, book)


def ensure_cursor(learner_id: str = "", book_id: str = "") -> dict[str, Any] | None:
    lid = (learner_id or "").strip() or _owner_id()
    book = (book_id or current_book_id(lid)).strip() or BOOK_ZHOU
    if not lid:
        return None
    cur = get_store().get_book_cursor(lid, book)
    if cur and (cur.get("atom_id") or "").strip():
        return cur
    first = first_atom_id(book)
    if not first:
        return None
    get_store().set_book_cursor(lid, book, first, status="active")
    return get_store().get_book_cursor(lid, book)


def _mapped(atom_id: str, book_id: str) -> dict[str, Any] | None:
    hit = best_l3(atom_id, book_id)
    if not hit:
        return None
    try:
        conf = float(hit.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < L3_MIN_CONF:
        return None
    l3_id = str(hit.get("l3_id") or "").strip()
    if not l3_id:
        return None
    return {"l3_id": l3_id, "confidence": conf}


def skip_unmapped(learner_id: str, book_id: str, start_atom: str) -> dict[str, Any]:
    """无 L3 或 confidence<0.6 则 skip 并前进；禁止卡死。"""
    seen: set[str] = set()
    atom_id = (start_atom or "").strip()
    skipped: list[str] = []
    store = get_store()
    while atom_id and atom_id not in seen:
        seen.add(atom_id)
        mapped = _mapped(atom_id, book_id)
        if mapped:
            store.set_book_cursor(lid=learner_id, book_id=book_id, atom_id=atom_id, status="active")
            return {
                "atom_id": atom_id,
                "l3_id": mapped["l3_id"],
                "confidence": mapped["confidence"],
                "skipped": skipped,
            }
        skipped.append(atom_id)
        store.mark_atom_status(learner_id, book_id, atom_id, "skipped")
        atom_id = next_atom_after(atom_id, book_id)
    store.set_book_cursor(lid=learner_id, book_id=book_id, atom_id=start_atom or "", status="exhausted")
    return {"atom_id": "", "l3_id": "", "confidence": 0.0, "skipped": skipped, "exhausted": True}


def resolve_advance_target(learner_id: str = "") -> dict[str, Any]:
    lid = (learner_id or "").strip() or _owner_id()
    book = current_book_id(lid)
    if not book_accepted(book):
        return {"ok": False, "error": "book_not_accepted", "book_id": book}
    cur = ensure_cursor(lid, book)
    if not cur:
        return {"ok": False, "error": "no_atoms", "book_id": book}
    status = (cur.get("status") or "").strip()
    if status in ("passed_book", "exhausted"):
        if book == BOOK_ZHOU and book_accepted(BOOK_FAN):
            get_store().set_learner_mode(lid, "comm", "advance", BOOK_FAN)
            return resolve_advance_target(lid)
        return {
            "ok": False,
            "error": "zhou_complete",
            "book_id": book,
            "hint": "周已完成且樊库未验收，15:00 不混库",
        }
    mapped = skip_unmapped(lid, book, cur.get("atom_id") or "")
    if not mapped.get("atom_id"):
        if book == BOOK_ZHOU and book_accepted(BOOK_FAN):
            get_store().set_learner_mode(lid, "comm", "advance", BOOK_FAN)
            get_store().set_book_cursor(lid, BOOK_ZHOU, cur.get("atom_id") or "", status="passed_book")
            return resolve_advance_target(lid)
        get_store().set_book_cursor(lid, book, cur.get("atom_id") or "", status="passed_book")
        return {
            "ok": False,
            "error": "zhou_complete",
            "book_id": book,
            "skipped": mapped.get("skipped") or [],
        }
    atom = get_atom(mapped["atom_id"], book) or {}
    spans = core_spans(mapped["atom_id"], book)
    return {
        "ok": True,
        "learner_id": lid,
        "book_id": book,
        "atom_id": mapped["atom_id"],
        "l3_id": mapped["l3_id"],
        "confidence": mapped["confidence"],
        "statement": atom.get("statement") or "",
        "name": atom.get("name") or "",
        "chapter": atom.get("chapter"),
        "n_core_spans": len(spans),
        "skipped": mapped.get("skipped") or [],
    }


def reserved_comm_spec(learner_id: str = "") -> dict[str, str] | None:
    """凌晨预留槽：当前原子 pin L3，不受薄弱配额。已有 pass/pending 则 None。"""
    if not advance_active("comm", learner_id):
        return None
    target = resolve_advance_target(learner_id)
    if not target.get("ok"):
        return None
    atom_id = target["atom_id"]
    book = target["book_id"]
    store = get_store()
    if store.count_atom_items("comm", atom_id, quality=("pass",)) >= 1:
        return None
    if store.count_atom_items("comm", atom_id, quality=("pending",)) >= 1:
        return None
    from learner.kp_registry import l2_for_l3

    l2 = l2_for_l3("comm", target["l3_id"]) or ""
    if not l2:
        return None
    return {
        "kp": l2,
        "technique": "",
        "subject": "comm",
        "content_subject": "comm",
        "l3_id": target["l3_id"],
        "atom_id": atom_id,
        "book_id": book,
        "reserved": "1",
    }


def ensure_reserved_comm_item(learner_id: str = "", *, judge: bool = True) -> dict[str, Any]:
    """当前原子若无 ready+pass，立刻预留出题并审判。不是 BANK_LIVE_FALLBACK（不换 KP、不 walk）。"""
    if not advance_active("comm", learner_id):
        return {"ok": False, "error": "not_advance"}
    target = resolve_advance_target(learner_id)
    if not target.get("ok"):
        return {"ok": False, "error": "no_target", "target": target}
    atom_id = (target.get("atom_id") or "").strip()
    if not atom_id:
        return {"ok": False, "error": "no_atom"}
    store = get_store()
    if store.count_atom_items("comm", atom_id, quality=("pass",)) >= 1:
        return {"ok": True, "skipped": True, "reason": "already_pass", "atom_id": atom_id}

    authored: dict[str, Any] | None = None
    spec = reserved_comm_spec(learner_id)
    if spec:
        from cultivate_bank import _author_spec

        authored = _author_spec("comm", spec)

    judged: list[dict[str, Any]] = []
    if judge:
        from cultivate_judge import judge_one_item

        pending = store.list_atom_items("comm", atom_id, quality=("pending",), limit=2)
        for it in pending:
            judged.append(judge_one_item(it, use_llm=True))

    n_pass = store.count_atom_items("comm", atom_id, quality=("pass",))
    return {
        "ok": n_pass >= 1,
        "atom_id": atom_id,
        "authored": authored,
        "judged": [
            {k: j.get(k) for k in ("ok", "item_id", "phase", "quality_tier", "error") if k in j or j.get(k) is not None}
            for j in judged
        ],
        "n_pass": n_pass,
        "error": None if n_pass >= 1 else (authored or {}).get("error") or "no_pass",
    }


def _gate_pass(prog: dict[str, Any]) -> str:
    """返回 passed|escaped|''。"""
    streak_c = int(prog.get("streak_correct") or 0)
    streak_w = int(prog.get("streak_incorrect") or 0)
    total_c = int(prog.get("total_correct") or 0)
    recent = prog.get("recent_verdicts") or []
    if not isinstance(recent, list):
        recent = []
    if streak_c >= 2:
        return "passed"
    last5 = [x for x in recent if x in ("correct", "wrong")][-5:]
    if total_c >= 3 and last5:
        rate = sum(1 for x in last5 if x == "correct") / float(len(last5))
        if rate >= 0.6:
            return "passed"
    if streak_w >= max(1, ESCAPE_K):
        return "escaped"
    return ""


def apply_atom_grade(
    *,
    learner_id: str,
    book_id: str,
    atom_id: str,
    slot: str,
    verdict: str,
    status: str,
    credit: float | None,
) -> dict[str, Any]:
    """只计 15:00 comm 的 applied + verdict=correct（credit 为空）。"""
    out = {"updated": False, "advanced": False, "status": ""}
    if (slot or "").strip().lower() != "comm":
        return out
    if (status or "").strip() != "applied":
        return out
    aid = (atom_id or "").strip()
    book = (book_id or "").strip()
    lid = (learner_id or "").strip() or _owner_id()
    if not aid or not book or not lid:
        return out
    is_correct = (verdict or "").strip() == "correct" and credit is None
    store = get_store()
    prog = store.touch_atom_progress(lid, book, aid, correct=is_correct)
    out["updated"] = True
    gate = _gate_pass(prog)
    out["status"] = gate or (prog.get("status") or "active")
    if not gate:
        return out
    nxt = next_atom_after(aid, book)
    store.mark_atom_status(lid, book, aid, gate)
    if nxt:
        store.set_book_cursor(lid, book, nxt, status="active")
        out["advanced"] = True
        out["next_atom_id"] = nxt
    else:
        if book == BOOK_ZHOU and book_accepted(BOOK_FAN):
            store.set_book_cursor(lid, book, aid, status="passed_book")
            store.set_learner_mode(lid, "comm", "advance", BOOK_FAN)
            first = first_atom_id(BOOK_FAN)
            if first:
                store.set_book_cursor(lid, BOOK_FAN, first, status="active")
                out["advanced"] = True
                out["next_atom_id"] = first
                out["book_id"] = BOOK_FAN
        else:
            store.set_book_cursor(lid, book, aid, status="passed_book")
            out["book_complete"] = True
    return out


def list_book_order_ids(book_id: str = BOOK_ZHOU) -> list[str]:
    return [str(r["id"]) for r in list_atoms_in_book_order(book_id)]
