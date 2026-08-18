"""CapabilityService：组装 LearnerParams，可选落 ability_snapshots。"""
from __future__ import annotations

from typing import Any, Optional

from .domain_map import DOMAINS, map_kp_to_domain
from .evidence import ADAPTER_ASSUMPTIONS, bundle_from_store
from .latent import estimate_latent
from .params import (
    AbilitySignal,
    DomainEta,
    LearnerParams,
    MasteryEntry,
    default_assumptions,
)


def estimate_eta_for_learner(
    store,
    user_id: str,
    *,
    learner_id: Optional[str] = None,
    days: int | None = 90,
    syllabus_path: str | None = None,
    domains: tuple[str, ...] = DOMAINS,
) -> tuple[list[DomainEta], dict[str, Any]]:
    """从 store attempts 估 η；返回 (DomainEta 列表, EvidenceBundle)。"""
    bundle = bundle_from_store(
        store,
        user_id,
        learner_id=learner_id or user_id,
        days=days,
        syllabus_path=syllabus_path,
    )
    latent = estimate_latent(bundle, domains=list(domains))
    counts: dict[str, int] = {d: 0 for d in domains}
    for it in bundle.get("items") or []:
        dom = it.get("domain")
        if dom in counts:
            counts[dom] += 1
    etas = [
        DomainEta(domain=d, eta=float(e), n_items=counts.get(d, 0))
        for d, e in zip(latent.domains, latent.eta_hat)
    ]
    return etas, bundle


def _mastery_entries(
    mastery_map: dict[str, float],
    *,
    syllabus_path: str | None = None,
    due_kps: Optional[set[str]] = None,
    states: Optional[dict[str, dict]] = None,
) -> list[MasteryEntry]:
    due_kps = due_kps or set()
    states = states or {}
    out: list[MasteryEntry] = []
    for kp, p in sorted(mastery_map.items()):
        if not kp or kp in ("无", "未分类"):
            continue
        st = states.get(kp) or {}
        opp = int(st.get("opportunity_count") or st.get("n") or 0)
        mastered = bool(st.get("is_mastered")) if "is_mastered" in st else (p >= 0.8 and opp >= 3)
        out.append(
            MasteryEntry(
                kp=kp,
                p_mastery=float(p),
                opportunity_count=opp,
                is_mastered=mastered,
                due=kp in due_kps,
                domain=map_kp_to_domain(kp, syllabus_path=syllabus_path),
            )
        )
    return out


def build_learner_params(
    store,
    user_id: str,
    *,
    learner_id: Optional[str] = None,
    days: int | None = 90,
    syllabus_path: str | None = None,
    ability_goal: str = "",
    item_form: str = "",
    subject: str = "",
    persist_snapshot: bool = False,
) -> LearnerParams:
    """统一入口：BKT mastery + 域 η → LearnerParams。"""
    lid = learner_id or user_id
    mastery_map = store.get_all_mastery(user_id) if hasattr(store, "get_all_mastery") else {}
    states: dict[str, dict] = {}
    if hasattr(store, "get_mastery_full"):
        try:
            states = store.get_mastery_full(user_id) or {}
        except Exception:
            states = {}

    due: set[str] = set()
    mastery = _mastery_entries(
        mastery_map, syllabus_path=syllabus_path, due_kps=due, states=states
    )
    etas, bundle = estimate_eta_for_learner(
        store,
        user_id,
        learner_id=lid,
        days=days,
        syllabus_path=syllabus_path,
    )
    ability = None
    if ability_goal:
        ability = AbilitySignal(goal=ability_goal, item_form=item_form, subject=subject)

    notes = tuple(ADAPTER_ASSUMPTIONS)
    params = LearnerParams(
        learner_id=lid,
        mastery=mastery,
        eta=etas,
        ability=ability,
        assumptions=default_assumptions(notes=notes),
        meta={
            "evidence": {
                "n_items": (bundle.get("meta") or {}).get("n_items", 0),
                "domains_present": (bundle.get("meta") or {}).get("domains_present", []),
                "missing_domains": (bundle.get("meta") or {}).get("missing_domains", []),
                "skipped": (bundle.get("meta") or {}).get("skipped", {}),
            }
        },
    )

    if persist_snapshot and hasattr(store, "add_ability_snapshot"):
        try:
            store.add_ability_snapshot(lid, params.to_dict())
        except Exception:
            pass
    return params


class CapabilityService:
    """薄服务对象，便于 bridge 注入。"""

    def __init__(self, store, *, syllabus_path: str | None = None):
        self.store = store
        self.syllabus_path = syllabus_path

    def params(self, user_id: str, **kwargs) -> LearnerParams:
        return build_learner_params(
            self.store,
            user_id,
            syllabus_path=kwargs.pop("syllabus_path", self.syllabus_path),
            **kwargs,
        )

    def evidence_bundle(self, user_id: str, **kwargs) -> dict:
        return bundle_from_store(
            self.store,
            user_id,
            syllabus_path=kwargs.pop("syllabus_path", self.syllabus_path),
            **kwargs,
        )
