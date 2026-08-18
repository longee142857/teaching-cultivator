"""选题侧：用域 η 给薄弱域轻微提权（不替代 BKT/weights）。"""
from __future__ import annotations

from typing import Iterable, Optional

from .domain_map import DOMAINS, map_kp_to_domain


def weak_domain_boosts(
    eta_by_domain: dict[str, float],
    *,
    scale: float = 0.12,
    domains: tuple[str, ...] = DOMAINS,
) -> dict[str, float]:
    """η 越低 boost 越大；无观测域 (n 缺省) 不在此函数处理。

    boost ∈ [0, scale]；相对最强域归一。
    """
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
            # 相对最强域的落差
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
    """LearnerParams → {domain: eta}，仅含 n_items>0 的域（避免空域乱提权）。"""
    out: dict[str, float] = {}
    for e in getattr(params, "eta", []) or []:
        if int(getattr(e, "n_items", 0) or 0) <= 0:
            continue
        out[str(e.domain)] = float(e.eta)
    return out
