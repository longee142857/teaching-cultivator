"""KP / subject → {calc, linalg, prob}（与 capability-prob adapters 对齐）。"""
from __future__ import annotations

import json
import os
from functools import lru_cache

DOMAINS = ("calc", "linalg", "prob")


def _default_syllabus() -> str:
    root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "syllabus_math.json")
    )
    return root


@lru_cache(maxsize=4)
def load_kp_l1_map(syllabus_path: str | None = None) -> dict[str, str]:
    path = syllabus_path or _default_syllabus()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, str] = {}
    for kp, meta in (data.get("kps") or {}).items():
        l1 = (meta or {}).get("l1")
        if l1 in DOMAINS:
            out[kp] = l1
            for alias in (meta or {}).get("aliases") or []:
                if isinstance(alias, str) and alias.strip():
                    out[alias.strip()] = l1
    return out


def map_kp_to_domain(kp: str, *, syllabus_path: str | None = None) -> str | None:
    """精确名 → l1；否则子串启发式（取最长匹配）。"""
    kp = (kp or "").strip()
    if not kp or kp in ("无", "未分类"):
        return None
    m = load_kp_l1_map(syllabus_path)
    if kp in m:
        return m[kp]
    best = None
    best_len = 0
    for name, dom in m.items():
        if name and name in kp and len(name) > best_len:
            best, best_len = dom, len(name)
    return best


def clear_domain_cache() -> None:
    load_kp_l1_map.cache_clear()
