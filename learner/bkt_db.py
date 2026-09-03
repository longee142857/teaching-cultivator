"""BKTLogger 的 SQLite 实现（BIG-TEACH-013）。

对外接口与 knowledge-system/lib/bkt.py 的 BKTLogger 对齐（get_user_history /
get_kp_mastery / get_all_kp_mastery / get_recent_correct / get_due_kps / record），
但读写落在 teaching.db 的 attempts + mastery_states，answer-log.jsonl 不再权威。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from bkt import KCState, _parse_ts as _bkt_parse_ts
except ImportError:  # 独立测试/云上缺 knowledge-system/lib 时回退
    _rel_lib = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "../../knowledge-system/lib")
    )
    if _rel_lib not in sys.path:
        sys.path.insert(0, _rel_lib)
    from bkt import KCState, _parse_ts as _bkt_parse_ts

from learner import db as _store


def _now_utc():
    return datetime.now(timezone.utc)


def _parse_ts(ts: str | None):
    return _bkt_parse_ts(ts)


class DbBKTLogger:
    """SQLite 版作答日志 + 掌握度读写。"""

    def __init__(self, store=None):
        self._store = store or _store.get_store()

    # ── 读接口（与 BKTLogger 对齐）──────────────────────────

    def get_user_history(self, user_id: str) -> list[dict]:
        return self._store.get_attempts(user_id)

    def get_kp_mastery(self, user_id: str, knowledge_point: str) -> Optional[KCState]:
        st = self._store.get_mastery(user_id, knowledge_point)
        if not st:
            return None
        return KCState.from_dict(st)

    def get_all_kp_mastery(self, user_id: str) -> dict[str, float]:
        return self._store.get_all_mastery(user_id)

    def get_recent_correct(self, user_id: str, knowledge_point: str) -> Optional[bool]:
        for r in reversed(self.get_user_history(user_id)):
            if r.get("knowledge_point") == knowledge_point and not r.get("quarantined"):
                return bool(r.get("correct"))
        return None

    def get_due_kps(self, user_id: str, now=None) -> set[str]:
        latest: dict[str, dict] = {}
        for r in self.get_user_history(user_id):
            kp = r.get("knowledge_point")
            if kp:
                latest[kp] = r
        due: set[str] = set()
        now_dt = _now_utc() if now is None else now
        for kp, r in latest.items():
            st = r.get("state") or {}
            dt = _parse_ts(st.get("due_ts"))
            if dt and dt <= now_dt:
                due.add(kp)
        return due

    # ── 写接口 ─────────────────────────────────────────────

    def record(
        self,
        user_id: str,
        knowledge_point: str,
        correct: bool,
        state: KCState,
        turn_id: str = "",
        conv_tag: str = "",
        subject: str = "",
        *,
        item_type: str = "unknown",
        credit: float | None = None,
        ref_id: str = "",
        force: bool = False,
        status: str = "applied",
        overrides: dict | None = None,
        push_id: int | None = None,
        item_id: int | None = None,
        cdp_results: list | None = None,
        confidence: float | None = None,
        user_answer: str = "",
        feedback: str = "",
        verdict: str = "",
    ) -> dict[str, Any]:
        mastery_before = state.p_mastery
        now_dt = _now_utc()
        if not force and not state._rate_limit_ok(now_dt):
            meta = {
                "applied": False,
                "reason": "rate_limited",
                "p_mastery": state.p_mastery,
            }
        else:
            meta = state.update(
                correct,
                item_type=item_type,
                credit=credit,
                ref_id=ref_id,
                now=now_dt,
                force=True,
                overrides=overrides,
            )

        entry = {
            "ts": _now_utc().isoformat(),
            "user_id": user_id,
            "turn_id": turn_id,
            "conv_tag": conv_tag,
            "knowledge_point": knowledge_point,
            "correct": correct,
            "item_type": item_type,
            "mastery_before": round(mastery_before, 4),
            "mastery_after": round(state.p_mastery, 4),
            "update_applied": bool(meta.get("applied")),
            "update_reason": meta.get("reason"),
            "status": status,
            "state": state.to_dict(),
        }
        if credit is not None:
            entry["credit"] = credit
        if ref_id:
            entry["ref_id"] = ref_id
        if subject:
            entry["subject"] = subject
        if cdp_results is not None:
            entry["cdp_results"] = cdp_results
        if confidence is not None:
            entry["confidence"] = confidence
        if user_answer:
            entry["user_answer"] = user_answer
        if feedback:
            entry["feedback"] = feedback
        if verdict:
            entry["verdict"] = verdict

        # 禁止静默挂到 latest push（会把旧题作答联错行）
        if push_id is None and item_id is None:
            print(
                f"[bkt_db] attempt without push_id/item_id "
                f"(user={user_id} kp={knowledge_point})"
            )
        self._store.add_attempt_entry(
            {**entry, "push_id": push_id, "item_id": item_id}
        )
        self._store.set_mastery(user_id, knowledge_point, state.to_dict(), entry["ts"])

        if cdp_results is not None:
            try:
                from learner.item_bank import learner_cdp_fail_summary

                fail_sum = learner_cdp_fail_summary(cdp_results)
                self._store.add_ability_snapshot(
                    user_id,
                    {
                        "kp_failures": [] if correct else [knowledge_point],
                        "technique_failures": fail_sum["technique_failures"],
                        "cdp_fail_ids": fail_sum["cdp_fail_ids"],
                        "at": entry["ts"],
                        "kp": knowledge_point,
                        "correct": correct,
                    },
                )
            except Exception:
                pass

        try:
            self._append_audit(entry, meta, subject)
        except Exception:
            pass
        return meta

    def _append_audit(self, entry: dict, meta: dict, subject: str) -> None:
        source = {
            "self_report_weak": "note_weak",
            "adjust_difficulty": "adjust_difficulty",
            "user_override": "override",
        }.get(entry.get("conv_tag", ""), "grade" if not entry.get("conv_tag") else entry.get("conv_tag"))
        audit = {
            "ts": entry["ts"],
            "kp": entry["knowledge_point"],
            "applied": bool(meta.get("applied")),
            "reason": meta.get("reason") or "",
            "source": source,
            "subject": subject or "",
            "item_type": entry.get("item_type", ""),
            "mastery_before": entry.get("mastery_before"),
            "mastery_after": entry.get("mastery_after"),
        }
        # 审计写学员目录旁路 JSONL（仅可观测性，不参与运行时逻辑；学员目录已 gitignore）
        try:
            from learner import paths as P
            sid = str(entry.get("user_id") or "").strip()
            if sid:
                d = os.path.join(P.learners_root(), P.safe_learner_id(sid))
            else:
                d = os.path.dirname(self._store.path)
            os.makedirs(d, exist_ok=True)
            audit_path = os.path.join(d, "param_audit.jsonl")
            with open(audit_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(audit, ensure_ascii=False) + "\n")
        except Exception:
            pass


def get_bkt_log(store=None) -> DbBKTLogger:
    return DbBKTLogger(store)
