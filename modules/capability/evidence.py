"""attempts → EvidenceBundle（只读；与 capability-prob adapters 对齐）。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Iterable, Optional

from .domain_map import DOMAINS, map_kp_to_domain
from .params import ItemIrtParams

_DIFF_TO_D = {
    "easy": -0.5,
    "简单": -0.5,
    "medium": 0.0,
    "中等": 0.0,
    "hard": 0.5,
    "困难": 0.5,
    "basic": -0.5,
    "intermediate": 0.0,
    "challenge": 0.5,
}

ADAPTER_ASSUMPTIONS = [
    "teaching 题参未标定：默认 a=1.0，d 由 difficulty 粗映射（缺省 0）",
    "事件 DAG/β 仍来自事件 YAML 先验，非从该学员拟合",
    "仅使用 applied 作答；跳过 quarantined / 未分类 / 空 KP",
]


def difficulty_to_d(diff: str | None) -> float:
    if not diff or not isinstance(diff, str):
        return 0.0
    key = diff.strip().lower()
    return _DIFF_TO_D.get(key, 0.0)


def resolve_item_irt(row: dict) -> ItemIrtParams:
    """从 attempt / item meta 解析 (a,d)。优先显式 irt，否则 difficulty 粗映射。"""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    if isinstance(row.get("irt"), dict):
        meta = {**meta, **row["irt"]}
    if "a" in meta and "d" in meta:
        return ItemIrtParams(
            a=float(meta["a"]),
            d=float(meta["d"]),
            domain=meta.get("domain"),
            source=str(meta.get("irt_source") or "meta"),
        )
    diff = row.get("difficulty") or row.get("item_type") or ""
    return ItemIrtParams(a=1.0, d=difficulty_to_d(diff), source="difficulty_map")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_ok(row: dict) -> bool:
    if row.get("quarantined"):
        return False
    status = row.get("status") or ""
    if status in ("pending", "audit_only", "quarantined", "audit"):
        return False
    if row.get("update_applied") is False:
        return False
    if row.get("correct") is None:
        return False
    kp = (row.get("knowledge_point") or "").strip()
    if not kp or kp in ("无", "未分类"):
        return False
    return True


def attempts_to_bundle(
    attempts: Iterable[dict],
    *,
    learner_id: str = "fixture",
    days: int | None = 90,
    syllabus_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = None
    if days is not None:
        cutoff = now - timedelta(days=days)

    items: list[dict] = []
    skipped = {"bad": 0, "no_domain": 0, "old": 0}
    for i, row in enumerate(attempts):
        if not _row_ok(row):
            skipped["bad"] += 1
            continue
        ts = _parse_ts(row.get("ts") or row.get("answered_at"))
        if cutoff and ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if cutoff and ts and ts < cutoff:
            skipped["old"] += 1
            continue
        kp = (row.get("knowledge_point") or "").strip()
        irt = resolve_item_irt(row)
        dom = irt.domain or map_kp_to_domain(kp, syllabus_path=syllabus_path)
        if dom is None:
            skipped["no_domain"] += 1
            continue
        items.append(
            {
                "item": i + 1,
                "domain": dom,
                "a": irt.a,
                "d": irt.d,
                "correct": 1 if row.get("correct") else 0,
                "kp": kp,
                "irt_source": irt.source,
            }
        )

    present = {it["domain"] for it in items}
    missing = [d for d in DOMAINS if d not in present]
    return {
        "learner_id": learner_id,
        "items": items,
        "meta": {
            "source": "teaching_capability",
            "n_items": len(items),
            "domains_present": sorted(present),
            "missing_domains": missing,
            "skipped": skipped,
        },
        "adapter_assumptions": list(ADAPTER_ASSUMPTIONS),
    }


def bundle_from_store(
    store,
    user_id: str,
    *,
    learner_id: Optional[str] = None,
    days: int | None = 90,
    syllabus_path: str | None = None,
) -> dict[str, Any]:
    attempts = store.get_attempts(user_id)
    return attempts_to_bundle(
        attempts,
        learner_id=learner_id or user_id,
        days=days,
        syllabus_path=syllabus_path,
    )
