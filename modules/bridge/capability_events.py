# -*- coding: utf-8 -*-
"""Capability Brain event catalog (defaults + mentor-writable overlays).

Stored at ``data/capability_events.json``. Mentors may upsert events via
``POST /api/v1/capability/events``; Brain page merges remote + built-ins.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9_\-]+")


def _data_dir() -> str:
    try:
        from config import DATA_DIR

        return DATA_DIR
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def events_path() -> str:
    override = (os.environ.get("CAPABILITY_EVENTS_PATH") or "").strip()
    if override:
        return override
    return os.path.join(_data_dir(), "capability_events.json")


def _slug(title: str, explicit: str = "") -> str:
    if explicit:
        s = explicit.strip().lower().replace(" ", "_")
        s = _SLUG_RE.sub("_", s).strip("_")
        return s[:64] or f"event_{int(time.time())}"
    # rough pinyin-less slug from latin bits + timestamp
    base = re.sub(r"\s+", "_", (title or "event").strip().lower())
    base = _SLUG_RE.sub("", base) or "event"
    return f"{base[:40]}_{int(time.time()) % 100000}"


def _normalize_event(raw: dict[str, Any], *, source: str = "mentor") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or raw.get("name") or "").strip()
    eid = str(raw.get("id") or raw.get("event_id") or "").strip()
    if not title and not eid:
        return None
    if not title:
        title = eid
    if not eid:
        eid = _slug(title)
    domains = raw.get("domains") or raw.get("domain") or []
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.replace("，", ",").split(",") if d.strip()]
    if not isinstance(domains, list):
        domains = []
    domains = [str(d).strip() for d in domains if str(d).strip()]
    if not domains:
        domains = ["comm"]

    try:
        p_hat = float(raw.get("p_hat") if raw.get("p_hat") is not None else raw.get("p") or 0.4)
    except (TypeError, ValueError):
        p_hat = 0.4
    p_hat = max(0.05, min(0.95, p_hat))
    ci = raw.get("ci")
    if not (isinstance(ci, (list, tuple)) and len(ci) == 2):
        lo = max(0.02, p_hat - 0.06)
        hi = min(0.98, p_hat + 0.06)
        ci = [round(lo, 3), round(hi, 3)]
    else:
        ci = [float(ci[0]), float(ci[1])]

    top_paths = raw.get("top_paths") if isinstance(raw.get("top_paths"), list) else []
    bottlenecks = raw.get("bottlenecks") if isinstance(raw.get("bottlenecks"), list) else []
    if not top_paths:
        gates = [f"{d}_mastery_gate" if d in ("calc", "linalg", "prob") else f"{d}_unit_gate" for d in domains[:3]]
        top_paths = [
            {"passed_gates": gates[:2], "failed_gates": gates[2:] or ["timed_mock_pass"], "freq": 0.24},
            {"passed_gates": gates[:1], "failed_gates": gates[1:] or ["timed_mock_pass"], "freq": 0.18},
            {"passed_gates": gates, "failed_gates": [], "freq": 0.12},
        ]
    if not bottlenecks:
        node = f"{domains[0]}_unit_gate" if domains else "timed_mock_pass"
        bottlenecks = [
            {"node": node, "when_fail": 220, "share": 0.28},
            {"node": "timed_mock_pass", "when_fail": 140, "share": 0.18},
        ]

    return {
        "id": eid,
        "title": title,
        "blurb": str(raw.get("blurb") or raw.get("note") or "").strip()
        or f"导师团写入 · 域 {', '.join(domains)}",
        "domains": domains,
        "p_hat": round(p_hat, 3),
        "ci": ci,
        "n_paths": int(raw.get("n_paths") or max(6, len(top_paths) + 3)),
        "top_paths": top_paths,
        "bottlenecks": bottlenecks,
        "source": source,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "author": str(raw.get("author") or raw.get("mentor") or "mentor").strip() or "mentor",
    }


def _read_store() -> dict[str, Any]:
    path = events_path()
    if not os.path.isfile(path):
        return {"version": 1, "events": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "events": []}
        ev = data.get("events")
        if not isinstance(ev, list):
            data["events"] = []
        return data
    except Exception:
        return {"version": 1, "events": []}


def _write_store(data: dict[str, Any]) -> None:
    path = events_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_events() -> dict[str, Any]:
    store = _read_store()
    events = [e for e in (store.get("events") or []) if isinstance(e, dict) and e.get("id")]
    return {
        "ok": True,
        "count": len(events),
        "events": events,
    }


def upsert_event(payload: dict[str, Any], *, author: str = "mentor") -> dict[str, Any]:
    body = dict(payload or {})
    if author and not body.get("author"):
        body["author"] = author
    ev = _normalize_event(body, source="mentor")
    if not ev:
        return {"ok": False, "error": "invalid_event", "hint": "need title or id"}
    store = _read_store()
    events = [e for e in (store.get("events") or []) if isinstance(e, dict)]
    replaced = False
    for i, old in enumerate(events):
        if str(old.get("id") or "") == ev["id"]:
            events[i] = ev
            replaced = True
            break
    if not replaced:
        events.append(ev)
    store["events"] = events
    store["version"] = int(store.get("version") or 1)
    store["updated_at"] = ev["updated_at"]
    _write_store(store)
    return {"ok": True, "upserted": ev, "replaced": replaced, "count": len(events)}


def delete_event(event_id: str) -> dict[str, Any]:
    eid = (event_id or "").strip()
    if not eid:
        return {"ok": False, "error": "missing id"}
    store = _read_store()
    events = [e for e in (store.get("events") or []) if isinstance(e, dict)]
    keep = [e for e in events if str(e.get("id") or "") != eid]
    if len(keep) == len(events):
        return {"ok": False, "error": "not_found", "id": eid}
    store["events"] = keep
    store["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_store(store)
    return {"ok": True, "deleted": eid, "count": len(keep)}


__all__ = [
    "delete_event",
    "events_path",
    "list_events",
    "upsert_event",
]
