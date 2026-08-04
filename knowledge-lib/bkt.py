"""贝叶斯知识追踪 (Bayesian Knowledge Tracing) — 约束版（BIG-TEACH-009）

每个知识点维护一个 KCState:
- P(L): 已掌握概率
- P(T): 学习率
- P(G): 猜对率（按题型在 update 时选用）
- P(S): 失误率

产品层约束（已批准默认包）:
- T 默认 0.2；MCQ G=0.25 / open G=0.10
- Δ⁺ / Δ⁻ 帽；答错不升
- mastered = p≥0.8 且 opportunity≥3 且 streak≥2
- due_ts 复查；同 L2 24h 内最多 5 次有效更新（RATE_LIMIT_MAX）

用法:
  from lib.bkt import KCState, BKTLogger

  kc = KCState()
  kc.update(True, item_type="mcq")
  print(kc.is_mastered)
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

ItemType = Literal["mcq", "open", "blank", "proof_outline", "unknown"]

# ── 已批准默认包 ──
DEFAULT_PRIOR = 0.2
DEFAULT_LEARN = 0.2
DEFAULT_SLIP = 0.1
DEFAULT_GUESS = 0.2  # unknown / 持久化展示用

G_BY_TYPE = {"mcq": 0.25, "open": 0.10, "blank": 0.18, "proof_outline": 0.08, "unknown": 0.20}
D_POS_BY_TYPE = {"mcq": 0.15, "open": 0.20, "blank": 0.18, "proof_outline": 0.18, "unknown": 0.15}
D_NEG = 0.25

# ── 遗忘 / 时间衰减（BIG-TEACH-012b #3）──
FORGET_HALF_LIFE_DAYS = 30.0
_FORGET_LAMBDA = math.log(2) / FORGET_HALF_LIFE_DAYS

# ── BKT 参数覆盖表路径（BIG-TEACH-012b #2）──
BKT_OVERRIDES_PATH: str | None = None
_BKT_OVERRIDES_CACHE: dict | None = None


def _load_bkt_overrides() -> dict:
    """从 BKT_OVERRIDES_PATH 加载运行时覆盖表（全局缓存）。"""
    global _BKT_OVERRIDES_CACHE
    if _BKT_OVERRIDES_CACHE is not None:
        return _BKT_OVERRIDES_CACHE
    path = BKT_OVERRIDES_PATH
    if not path:
        _BKT_OVERRIDES_CACHE = {}
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            _BKT_OVERRIDES_CACHE = json.load(f)
    except (OSError, json.JSONDecodeError):
        _BKT_OVERRIDES_CACHE = {}
    return _BKT_OVERRIDES_CACHE


def compute_forget(p_mastery: float, last_update_ts: str | None, *,
                   half_life_days: float = FORGET_HALF_LIFE_DAYS,
                   prior: float = DEFAULT_PRIOR) -> float:
    """计算考虑时间衰减后的有效掌握度（不修改存储值）。

    p_eff = prior + (p - prior) * exp(-λ * Δt)
    λ = ln(2) / half_life_days
    """
    if not last_update_ts:
        return p_mastery
    dt = _parse_ts(last_update_ts)
    if dt is None:
        return p_mastery
    now = datetime.now(timezone.utc)
    delta_days = (now - dt).total_seconds() / 86400
    if delta_days <= 0:
        return p_mastery
    lam = math.log(2) / half_life_days
    return prior + (p_mastery - prior) * math.exp(-lam * delta_days)
MASTERED_P = 0.80
MASTERED_MIN_OPP = 3
MASTERED_MIN_STREAK = 2
RATE_LIMIT_HOURS = 24
RATE_LIMIT_MAX = 5
REF_WINDOW = 8


def _now_utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


class KCState:
    """单个知识点的掌握度状态"""

    def __init__(
        self,
        p_mastery: float = DEFAULT_PRIOR,
        p_learn: float = DEFAULT_LEARN,
        p_guess: float = DEFAULT_GUESS,
        p_slip: float = DEFAULT_SLIP,
    ):
        self.p_mastery = float(p_mastery)
        self.p_learn = float(p_learn)
        self.p_guess = float(p_guess)
        self.p_slip = float(p_slip)
        self.opportunity_count = 0
        self.streak_correct = 0
        self.last_update_ts: Optional[str] = None
        self.due_ts: Optional[str] = None
        self.recent_ref_ids: list[str] = []
        # 防刷：滚动窗口内有效更新时间戳（ISO）
        self._recent_update_ts: list[str] = []

    @property
    def p_effective(self) -> float:
        """有效掌握度（含时间衰减，不修改存储值）。"""
        return compute_forget(self.p_mastery, self.last_update_ts)

    def update(
        self,
        is_correct: bool,
        *,
        item_type: str = "unknown",
        credit: float | None = None,
        ref_id: str = "",
        now: datetime | None = None,
        force: bool = False,
        overrides: dict | None = None,
    ) -> dict[str, Any]:
        """一次作答后更新掌握度。返回 {applied, reason, ...}。

        防刷在 BKTLogger.record 层执行；此处 force 仅保留兼容。
        overrides 可含 p_slip / p_learn 覆盖表值（BIG-TEACH-012b #2）。
        """
        now_dt = _now_utc(now)
        now_iso = now_dt.isoformat()
        _ = force  # 兼容旧调用

        itype = item_type if item_type in G_BY_TYPE else "unknown"
        G = G_BY_TYPE[itype]
        S = overrides.get("p_slip", self.p_slip) if overrides else self.p_slip
        T = overrides.get("p_learn", self.p_learn) if overrides else self.p_learn
        d_pos = D_POS_BY_TYPE[itype]
        self.p_guess = G  # 记录本次使用的 G

        # 部分正确 → credit 缩放正向步长
        if credit is not None:
            try:
                c = float(credit)
            except (TypeError, ValueError):
                c = 1.0 if is_correct else 0.0
            c = max(0.0, min(1.0, c))
            if 0.0 < c < 1.0:
                is_correct = True
                d_pos = d_pos * c
            elif c <= 0.0:
                is_correct = False
            else:
                is_correct = True

        p = self.p_mastery
        if is_correct:
            denom = p * (1 - S) + (1 - p) * G
            posterior = (p * (1 - S)) / denom if denom > 0 else p
            raw = posterior + (1 - posterior) * T
            p_new = min(raw, p + d_pos, 1.0)
            self.streak_correct = self.streak_correct + 1
        else:
            denom = p * S + (1 - p) * (1 - G)
            posterior = (p * S) / denom if denom > 0 else p
            raw = posterior + (1 - posterior) * T
            # 答错不升，再套 Δ⁻
            p_new = min(raw, p)
            p_new = max(p_new, p - D_NEG, 0.0)
            self.streak_correct = 0

        self.p_mastery = p_new
        self.opportunity_count += 1
        self.last_update_ts = now_iso
        self._recent_update_ts.append(now_iso)
        self._trim_rate_window(now_dt)

        if ref_id:
            refs = [r for r in self.recent_ref_ids if r != ref_id]
            refs.insert(0, ref_id)
            self.recent_ref_ids = refs[:REF_WINDOW]

        self._set_due(is_correct=is_correct, now_dt=now_dt)

        return {
            "applied": True,
            "reason": "ok",
            "item_type": itype,
            "p_mastery": self.p_mastery,
            "is_mastered": self.is_mastered,
        }

    def _rate_limit_ok(self, now_dt: datetime) -> bool:
        self._trim_rate_window(now_dt)
        return len(self._recent_update_ts) < RATE_LIMIT_MAX

    def _trim_rate_window(self, now_dt: datetime) -> None:
        cutoff = now_dt - timedelta(hours=RATE_LIMIT_HOURS)
        kept = []
        for ts in self._recent_update_ts:
            dt = _parse_ts(ts)
            if dt and dt >= cutoff:
                kept.append(ts)
        self._recent_update_ts = kept

    def _set_due(self, *, is_correct: bool, now_dt: datetime) -> None:
        if not is_correct:
            delta = timedelta(days=1)
        elif not self.is_mastered:
            delta = timedelta(days=1, hours=12)  # 1–2 天中位
        elif self.opportunity_count <= MASTERED_MIN_OPP + 1:
            delta = timedelta(days=7)  # 刚掌握：5–9 中位（+7d 替代 +5d）
        else:
            delta = timedelta(days=21)  # 稳定：14–30 中位
        self.due_ts = (now_dt + delta).isoformat()

    @property
    def is_mastered(self) -> bool:
        return (
            self.p_mastery >= MASTERED_P
            and self.opportunity_count >= MASTERED_MIN_OPP
            and self.streak_correct >= MASTERED_MIN_STREAK
        )

    @property
    def difficulty(self) -> str:
        if self.p_mastery < 0.3:
            return "basic"
        if self.p_mastery < 0.7:
            return "intermediate"
        return "challenge"

    def is_due(self, now: datetime | None = None) -> bool:
        due = _parse_ts(self.due_ts)
        if due is None:
            return False
        return due <= _now_utc(now)

    def distinct_ref_count(self) -> int:
        return len({r for r in self.recent_ref_ids if r})

    def to_dict(self) -> dict:
        return {
            "p_mastery": round(self.p_mastery, 4),
            "p_learn": self.p_learn,
            "p_guess": self.p_guess,
            "p_slip": self.p_slip,
            "opportunity_count": self.opportunity_count,
            "streak_correct": self.streak_correct,
            "last_update_ts": self.last_update_ts,
            "due_ts": self.due_ts,
            "recent_ref_ids": list(self.recent_ref_ids),
            "recent_update_ts": list(self._recent_update_ts),
            "is_mastered": self.is_mastered,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KCState":
        kc = cls(
            p_mastery=d.get("p_mastery", DEFAULT_PRIOR),
            p_learn=d.get("p_learn", DEFAULT_LEARN),
            p_guess=d.get("p_guess", DEFAULT_GUESS),
            p_slip=d.get("p_slip", DEFAULT_SLIP),
        )
        kc.opportunity_count = int(d.get("opportunity_count", 0) or 0)
        kc.streak_correct = int(d.get("streak_correct", 0) or 0)
        kc.last_update_ts = d.get("last_update_ts")
        kc.due_ts = d.get("due_ts")
        refs = d.get("recent_ref_ids") or []
        if isinstance(refs, list):
            kc.recent_ref_ids = [str(x) for x in refs if x][:REF_WINDOW]
        recent_u = d.get("recent_update_ts") or []
        if isinstance(recent_u, list):
            kc._recent_update_ts = [str(x) for x in recent_u if x]
        # 兼容旧 log：有 last_update 但无窗口时塞一条
        if not kc._recent_update_ts and kc.last_update_ts:
            kc._recent_update_ts = [kc.last_update_ts]
        return kc


class BKTLogger:
    """作答日志记录"""

    def __init__(self, path: str):
        self.path = path

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
    ) -> dict[str, Any]:
        """记录一次作答并更新 state。返回 update meta。

        overrides 被透传给 state.update（BIG-TEACH-012b #2）。
        """
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
            "ts": datetime.now(timezone.utc).isoformat(),
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
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 可观测性：每次 record 追加一行结构化审计，便于反查参数变化来源
        try:
            audit_path = os.path.join(os.path.dirname(self.path), "param_audit.jsonl")
            source = {
                "self_report_weak": "note_weak",
                "adjust_difficulty": "adjust_difficulty",
                "user_override": "override",
            }.get(conv_tag, "grade" if not conv_tag else conv_tag)
            audit = {
                "ts": entry["ts"],
                "kp": knowledge_point,
                "applied": bool(meta.get("applied")),
                "reason": meta.get("reason") or "",
                "source": source,
                "subject": subject or "",
                "item_type": item_type,
                "mastery_before": round(mastery_before, 4),
                "mastery_after": round(state.p_mastery, 4),
            }
            with open(audit_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(audit, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return meta

    def get_user_history(self, user_id: str) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                out = []
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("user_id") == user_id:
                        out.append(row)
                return out
        except FileNotFoundError:
            return []

    def get_kp_mastery(self, user_id: str, knowledge_point: str) -> Optional[KCState]:
        records = [
            e
            for e in self.get_user_history(user_id)
            if e.get("knowledge_point") == knowledge_point
            and not e.get("quarantined")
        ]
        if not records:
            return None
        state_dict = records[-1].get("state")
        if state_dict:
            return KCState.from_dict(state_dict)
        # 旧格式：用当前公式回放（仅兜底）；跳过 pending/audit/未应用行
        skip_status = {"pending", "audit"}
        superseded = {
            str(r.get("supersedes_ts"))
            for r in records
            if r.get("supersedes_ts")
        }
        kc = KCState()
        for r in records:
            if r.get("status") in skip_status:
                continue
            if r.get("update_applied") is False:
                continue
            ts = str(r.get("ts") or "")
            if ts in superseded:
                continue
            if not isinstance(r.get("correct"), bool):
                continue
            kc.update(
                bool(r.get("correct")),
                item_type=str(r.get("item_type") or "unknown"),
                credit=r.get("credit"),
                ref_id=str(r.get("ref_id") or ""),
                force=True,
            )
        return kc

    def get_all_kp_mastery(self, user_id: str) -> dict[str, float]:
        kps: dict[str, float] = {}
        for r in self.get_user_history(user_id):
            kp = r.get("knowledge_point")
            if not kp or kp == "未分类" or r.get("quarantined"):
                continue
            ma = r.get("mastery_after")
            # 跳过 audit/未应用等无 mastery 的日志（如 adjust_difficulty 审计记录）
            if ma is None:
                continue
            kps[kp] = ma
        return kps

    def get_recent_correct(self, user_id: str, knowledge_point: str) -> Optional[bool]:
        for r in reversed(self.get_user_history(user_id)):
            if r.get("knowledge_point") == knowledge_point:
                return bool(r.get("correct"))
        return None

    def get_due_kps(self, user_id: str, now: datetime | None = None) -> set[str]:
        """Return L2 keys whose due_ts is reached (from latest state per kp)."""
        latest: dict[str, dict] = {}
        for r in self.get_user_history(user_id):
            kp = r.get("knowledge_point")
            if kp:
                latest[kp] = r
        due: set[str] = set()
        now_dt = _now_utc(now)
        for kp, r in latest.items():
            st = r.get("state") or {}
            due_ts = st.get("due_ts")
            dt = _parse_ts(due_ts)
            if dt and dt <= now_dt:
                due.add(kp)
        return due
