"""题参 IRT 附着（未标定时 a=1，d←difficulty）。"""
from __future__ import annotations

from typing import Any, Optional

from .domain_map import map_kp_to_domain
from .evidence import difficulty_to_d
from .params import ItemIrtParams


def build_irt_meta(
    *,
    kp: str = "",
    difficulty: str = "",
    syllabus_path: str | None = None,
    a: float | None = None,
    d: float | None = None,
) -> dict[str, Any]:
    """写入 items.meta['irt'] 的字典。"""
    domain = map_kp_to_domain(kp, syllabus_path=syllabus_path) if kp else None
    if a is not None and d is not None:
        irt = ItemIrtParams(a=float(a), d=float(d), domain=domain, source="explicit")
    else:
        irt = ItemIrtParams(
            a=1.0,
            d=difficulty_to_d(difficulty),
            domain=domain,
            source="difficulty_map",
        )
    out = irt.to_dict()
    return {"irt": out}


def merge_irt_into_meta(
    meta: Optional[dict],
    *,
    kp: str = "",
    difficulty: str = "",
    syllabus_path: str | None = None,
) -> dict[str, Any]:
    base = dict(meta or {})
    if isinstance(base.get("irt"), dict) and "a" in base["irt"] and "d" in base["irt"]:
        # 已有显式题参则只补 domain
        if not base["irt"].get("domain") and kp:
            dom = map_kp_to_domain(kp, syllabus_path=syllabus_path)
            if dom:
                base["irt"] = {**base["irt"], "domain": dom}
        return base
    base.update(build_irt_meta(kp=kp, difficulty=difficulty, syllabus_path=syllabus_path))
    return base
