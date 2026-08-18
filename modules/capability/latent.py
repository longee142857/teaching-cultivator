"""IRT 潜特质估计（自 capability-prob/engine/latent.py 同步）。

运行时副本：避免跨仓 import 叠仓。学术形式化与 Gate 仍以 capability-prob 为准；
改估计式时两边应同 PR / 同笔记更新。
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class LatentResult:
    eta_hat: list[float]
    domains: list[str]


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def irt_mle(
    y: list[int],
    a: list[float],
    d: list[float],
    prior_sigma: float = 3.0,
    tol: float = 1e-8,
    maxit: int = 100,
) -> float:
    """单域 MAP：Newton-Raphson 解负对数后验。"""
    eta = 0.0
    inv_var = 1.0 / (prior_sigma ** 2)
    for _ in range(maxit):
        fp = eta * inv_var
        fpp = inv_var
        for yj, aj, dj in zip(y, a, d):
            p = _logistic(aj * eta + dj)
            fp -= aj * (yj - p)
            fpp += aj * aj * p * (1.0 - p)
        if fpp <= 1e-12:
            break
        step = fp / fpp
        eta -= step
        if abs(step) < tol:
            break
    return eta


def estimate_latent(bundle: dict, domains: list[str] | None = None) -> LatentResult:
    """从 EvidenceBundle 估每个域 η̂。"""
    items = bundle.get("items", [])
    by_domain: dict[str, tuple[list[int], list[float], list[float]]] = {}
    for it in items:
        dom = it["domain"]
        if dom not in by_domain:
            by_domain[dom] = ([], [], [])
        yj = 1 if it["correct"] else 0
        by_domain[dom][0].append(yj)
        by_domain[dom][1].append(float(it["a"]))
        by_domain[dom][2].append(float(it["d"]))
    if domains is None:
        domains = list(by_domain.keys())
    eta_hat = []
    for dom in domains:
        y, a, d = by_domain.get(dom, ([], [], []))
        eta_hat.append(irt_mle(y, a, d) if y else 0.0)
    return LatentResult(eta_hat=eta_hat, domains=domains)
