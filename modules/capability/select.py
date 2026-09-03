"""选题侧：结合模型打分（BKT L2 + 域 η + 技巧缺口 + 题质量）。

主公式（推送抽题）::

    kp_need = weight×(1−mastery) + tech_boost + η_domain_boost
              （due×3；近轮同 KP×0.05，与 pick_kp_weighted 对齐）
    item_score = quality′ + α·kp_need + prefer_kp_bonus + prefer_tech_bonus

η 仅对有作答观测的域提权；不把 mastery/η 当事件成功概率。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .domain_map import DOMAINS, map_kp_to_domain

# ── 可调系数（部署可用 env 覆盖的入口在 item_bank）──
ETA_BOOST_SCALE = 0.15
KP_NEED_WEIGHT = 1.0
PREFER_KP_BONUS = 0.40
PREFER_TECH_BONUS = 0.20
DUE_MULT = 3.0
RECENT_MULT = 0.05
DEFAULT_MASTERY = 0.2
DEFAULT_WEIGHT = 1.0
TECH_FAIL_BOOST = 0.15


def weak_domain_boosts(
    eta_by_domain: dict[str, float],
    *,
    scale: float = ETA_BOOST_SCALE,
    domains: tuple[str, ...] = DOMAINS,
) -> dict[str, float]:
    """η 越低 boost 越大；boost ∈ [0, scale]。"""
    if not eta_by_domain:
        return {d: 0.0 for d in domains}
    vals = [float(eta_by_domain.get(d, 0.0)) for d in domains if d in eta_by_domain]
    if not vals:
        return {d: 0.0 for d in domains}
    hi = max(vals)
    lo = min(vals)
    span = hi - lo
    out: dict[str, float] = {}
    for d in domains:
        if d not in eta_by_domain:
            out[d] = 0.0
            continue
        if span < 1e-9:
            out[d] = 0.0
        else:
            out[d] = scale * (hi - float(eta_by_domain[d])) / span
    return out


def domain_boost_for_kp(
    kp: str,
    boosts: dict[str, float],
    *,
    syllabus_path: str | None = None,
) -> float:
    dom = map_kp_to_domain(kp, syllabus_path=syllabus_path)
    if not dom:
        return 0.0
    return float(boosts.get(dom, 0.0))


def eta_map_from_params(params) -> dict[str, float]:
    """LearnerParams → {domain: eta}，仅含 n_items>0 的域。"""
    out: dict[str, float] = {}
    for e in getattr(params, "eta", []) or []:
        if int(getattr(e, "n_items", 0) or 0) <= 0:
            continue
        out[str(e.domain)] = float(e.eta)
    return out


@dataclass
class PickContext:
    """一次抽题/补货共用的学员侧信号。"""

    learner_id: str = ""
    subject: str = "math"
    mastery: dict[str, float] = field(default_factory=dict)
    kp_weights: dict[str, float] = field(default_factory=dict)
    tech_boost: dict[str, float] = field(default_factory=dict)
    domain_boosts: dict[str, float] = field(default_factory=dict)
    due_kps: set[str] = field(default_factory=set)
    recent_kps: list[str] = field(default_factory=list)
    syllabus_path: str | None = None
    eta_by_domain: dict[str, float] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)


def score_kp_need(
    kp: str,
    ctx: PickContext,
    *,
    rotate_n: int = 3,
) -> float:
    """单 KP 需求分（越大越该练/该补）。"""
    try:
        w = float(ctx.kp_weights.get(kp, DEFAULT_WEIGHT))
    except (TypeError, ValueError):
        w = DEFAULT_WEIGHT
    if w < 0:
        w = 0.0
    m = ctx.mastery.get(kp)
    if m is None:
        m = DEFAULT_MASTERY
    m = max(0.0, min(1.0, float(m)))
    score = w * (1.0 - m)
    score += float(ctx.tech_boost.get(kp, 0.0))
    score += domain_boost_for_kp(kp, ctx.domain_boosts, syllabus_path=ctx.syllabus_path)
    if kp in ctx.due_kps:
        score *= DUE_MULT
    if kp in (ctx.recent_kps or [])[:rotate_n]:
        score *= RECENT_MULT
    if score < 1e-9:
        score = 1e-9
    return score


def quality_component(item: dict) -> float:
    try:
        sc = float(item.get("quality_score") if item.get("quality_score") is not None else 1.0)
    except (TypeError, ValueError):
        sc = 1.0
    if (item.get("quality_tier") or "") == "poor":
        sc = min(sc, 0.12)
    return max(0.0, sc)


def score_ready_item(
    item: dict,
    ctx: PickContext,
    *,
    prefer_kp: str = "",
    prefer_technique: str = "",
    kp_need_weight: float = KP_NEED_WEIGHT,
    prefer_kp_bonus: float = PREFER_KP_BONUS,
    prefer_tech_bonus: float = PREFER_TECH_BONUS,
) -> float:
    """ready 题综合分：质量 + KP 需求 + 软偏好。"""
    kp = (item.get("kp") or "").strip()
    need = score_kp_need(kp, ctx) if kp else DEFAULT_WEIGHT * (1.0 - DEFAULT_MASTERY)
    score = quality_component(item) + kp_need_weight * need
    pref_kp = (prefer_kp or "").strip()
    if pref_kp and kp == pref_kp:
        score += prefer_kp_bonus
    pref_tech = (prefer_technique or "").strip()
    if pref_tech:
        techs = item.get("techniques") or []
        if isinstance(techs, str):
            try:
                import json

                techs = json.loads(techs)
            except Exception:
                techs = []
        if pref_tech in [str(t) for t in (techs or [])]:
            score += prefer_tech_bonus
    return score


def rank_kps(ctx: PickContext, *, limit: int = 8) -> list[tuple[str, float]]:
    keys = list(ctx.kp_weights.keys()) if ctx.kp_weights else list(ctx.mastery.keys())
    ranked = [(kp, score_kp_need(str(kp), ctx)) for kp in keys if str(kp).strip()]
    ranked.sort(key=lambda x: -x[1])
    return ranked[:limit]


def pick_best_item(
    items: list[dict],
    ctx: PickContext,
    *,
    prefer_kp: str = "",
    prefer_technique: str = "",
) -> tuple[Optional[dict], float]:
    if not items:
        return None, 0.0
    pool = [
        it for it in items if (it.get("quality_tier") or "") == "pass"
    ]
    if not pool:
        return None, 0.0
    pref_kp = (prefer_kp or "").strip()
    if pref_kp:
        matched = [
            it for it in pool if (it.get("kp") or "").strip() == pref_kp
        ]
        if matched:
            pool = matched
    best = None
    best_sc = float("-inf")
    for it in pool:
        sc = score_ready_item(
            it, ctx, prefer_kp=prefer_kp, prefer_technique=prefer_technique
        )
        iid = int(it.get("id") or 0)
        if best is None or sc > best_sc + 1e-12 or (
            abs(sc - best_sc) <= 1e-12 and iid < int(best.get("id") or 0)
        ):
            best_sc = sc
            best = it
    return best, best_sc


def weighted_choice_kp(
    ctx: PickContext,
    *,
    rng: Any = None,
    rotate_n: int = 3,
) -> Optional[str]:
    """与历史 pick_kp_weighted 同分布族，但分数含 η/技巧。"""
    import random

    if rng is None:
        rng = random
    scores = rank_kps(ctx, limit=10_000)
    # re-apply rotate inside score_kp_need already; rank_kps uses full list
    if not scores:
        return None
    # rebuild with rotate_n explicit
    pairs = [(kp, score_kp_need(kp, ctx, rotate_n=rotate_n)) for kp, _ in scores]
    pairs = [(k, s) for k, s in pairs if s > 0]
    if not pairs:
        return None
    total = sum(s for _, s in pairs)
    r = rng.random() * total
    acc = 0.0
    for kp, s in pairs:
        acc += s
        if r <= acc:
            return kp
    return pairs[-1][0]
