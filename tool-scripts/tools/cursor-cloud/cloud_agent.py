#!/usr/bin/env python3
"""Cloud Cursor agent lifecycle CLI (isolated bank-workshop toolkit).

Commands: list | launch | send | wait | archive | get

Auth: Basic with CURSOR_API_KEY as username and empty password.
Never writes secrets to state or stdout.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://api.cursor.com"
DEFAULT_REPO = "https://github.com/longee142857/teaching-cultivator"
DEFAULT_REF = "master"
DEFAULT_MODEL = "composer-2.5"
NAME_PREFIX = "bank-workshop-"
POLL_INTERVAL_SEC = 45
WAIT_TIMEOUT_SEC = 45 * 60
BUSY_RETRY_SEC = 15

ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "data" / "cloud-agents-state.json"
LOAD_KEY = ROOT / "scripts" / "load_key.py"


def _ensure_key() -> str:
    key = os.environ.get("CURSOR_API_KEY")
    if key:
        return key
    if LOAD_KEY.is_file():
        sys.path.insert(0, str(LOAD_KEY.parent))
        from load_key import load_cursor_api_key  # type: ignore

        return load_cursor_api_key()
    raise SystemExit("CURSOR_API_KEY not set and scripts/load_key.py not found")


def _auth_header(key: str) -> str:
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    query: Optional[dict] = None,
    timeout: int = 120,
) -> tuple[int, Any]:
    key = _ensure_key()
    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = None
    headers = {
        "Authorization": _auth_header(key),
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw.strip() else {}
            return resp.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {"error": {"message": raw}}
        except json.JSONDecodeError:
            payload = {"error": {"code": "http_error", "message": raw}}
        return e.code, payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_state() -> list[dict]:
    if not STATE_PATH.exists():
        return []
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_state(items: list[dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _upsert_state(entry: dict) -> None:
    entry = {k: v for k, v in entry.items() if v is not None}
    items = _load_state()
    aid = entry.get("id")
    found = False
    for i, old in enumerate(items):
        if old.get("id") == aid:
            merged = {**old, **entry}
            items[i] = merged
            found = True
            break
    if not found:
        items.append(entry)
    _save_state(items)


def _error_code(payload: Any) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("code") or "")
    return ""


def _pr_url_from_run(run: dict) -> Optional[str]:
    git = run.get("git") or {}
    branches = git.get("branches") or []
    for b in branches:
        if isinstance(b, dict) and b.get("prUrl"):
            return b["prUrl"]
    return None


def cmd_list(args: argparse.Namespace) -> int:
    query: dict[str, Any] = {"limit": args.limit}
    if args.include_archived is not None:
        query["includeArchived"] = "true" if args.include_archived else "false"
    if args.cursor:
        query["cursor"] = args.cursor
    status, payload = _request("GET", "/v1/agents", query=query)
    if status != 200:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    items = payload.get("items") or []
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"agents: {len(items)}" + (f"  nextCursor={payload.get('nextCursor')}" if payload.get("nextCursor") else ""))
        for a in items:
            name = a.get("name") or ""
            print(
                f"  {a.get('id')}\t{a.get('status')}\t{name}\t"
                f"latestRun={a.get('latestRunId') or '-'}\t{a.get('url') or ''}"
            )
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    status, payload = _request("GET", f"/v1/agents/{args.id}")
    if status != 200:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    _upsert_state(
        {
            "id": payload.get("id"),
            "name": payload.get("name"),
            "status": payload.get("status"),
            "last_run_id": payload.get("latestRunId"),
            "updated_at": payload.get("updatedAt"),
        }
    )
    return 0


def _find_active_by_name(name: str) -> Optional[dict]:
    cursor = None
    while True:
        query: dict[str, Any] = {"limit": 100, "includeArchived": "false"}
        if cursor:
            query["cursor"] = cursor
        status, payload = _request("GET", "/v1/agents", query=query)
        if status != 200:
            raise RuntimeError(f"list agents failed: {payload}")
        for a in payload.get("items") or []:
            if a.get("status") == "ARCHIVED":
                continue
            aname = a.get("name") or ""
            if aname == name:
                return a
            if name.startswith(NAME_PREFIX) and aname == name:
                return a
        cursor = payload.get("nextCursor")
        if not cursor:
            break
    return None


def cmd_launch(args: argparse.Namespace) -> int:
    name = args.name
    prompt_text = args.prompt
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt_text:
        print("launch requires --prompt or --prompt-file", file=sys.stderr)
        return 2

    if not args.force_new and name.startswith(NAME_PREFIX):
        existing = _find_active_by_name(name)
        if existing and (existing.get("name") or "") == name and str(existing.get("status") or "").upper() != "ARCHIVED":
            print(
                f"RESUME existing agent {existing['id']} name={existing.get('name')} "
                f"(status={existing.get('status')}); sending follow-up instead of create"
            )
            args.id = existing["id"]
            args.prompt = prompt_text
            args.prompt_file = None
            rc = cmd_send(args)
            if rc == 0:
                _upsert_state(
                    {
                        "id": existing["id"],
                        "name": existing.get("name") or name,
                        "role": args.role,
                        "status": existing.get("status"),
                        "resumed_at": _now_iso(),
                    }
                )
            return rc

    body: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "name": name,
        "model": {"id": args.model},
        "repos": [
            {
                "url": args.repo,
                "startingRef": args.ref,
            }
        ],
        "autoCreatePR": True,
        "skipReviewerRequest": True,
    }
    status, payload = _request("POST", "/v1/agents", body=body)
    if status not in (200, 201):
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    agent = payload.get("agent") or {}
    run = payload.get("run") or {}
    entry = {
        "id": agent.get("id"),
        "name": agent.get("name") or name,
        "role": args.role,
        "created_at": agent.get("createdAt") or _now_iso(),
        "last_run_id": run.get("id") or agent.get("latestRunId"),
        "pr_url": _pr_url_from_run(run),
        "status": agent.get("status"),
        "url": agent.get("url"),
    }
    _upsert_state(entry)
    print(json.dumps({"agent": agent, "run": run, "state": entry}, ensure_ascii=False, indent=2))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    prompt_text = args.prompt
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt_text:
        print("send requires --prompt or --prompt-file", file=sys.stderr)
        return 2
    body: dict[str, Any] = {"prompt": {"text": prompt_text}}
    agent_id = args.id
    started = time.time()
    while True:
        status, payload = _request("POST", f"/v1/agents/{agent_id}/runs", body=body)
        if status in (200, 201):
            run = payload.get("run") or payload
            _upsert_state(
                {
                    "id": agent_id,
                    "last_run_id": run.get("id"),
                    "pr_url": _pr_url_from_run(run) or None,
                    "last_send_at": _now_iso(),
                }
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if status == 409 and _error_code(payload) == "agent_busy":
            if time.time() - started > WAIT_TIMEOUT_SEC:
                print("send: agent_busy until timeout", file=sys.stderr)
                return 1
            print(f"agent_busy; retry in {BUSY_RETRY_SEC}s...", file=sys.stderr)
            time.sleep(BUSY_RETRY_SEC)
            continue
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def cmd_wait(args: argparse.Namespace) -> int:
    agent_id = args.id
    run_id = args.run_id
    if not run_id:
        for e in _load_state():
            if e.get("id") == agent_id and e.get("last_run_id"):
                run_id = e["last_run_id"]
                break
        if not run_id:
            st, ag = _request("GET", f"/v1/agents/{agent_id}")
            if st != 200:
                print(json.dumps(ag, ensure_ascii=False, indent=2), file=sys.stderr)
                return 1
            run_id = ag.get("latestRunId")
        if not run_id:
            print("no run_id available to wait on", file=sys.stderr)
            return 2

    terminal = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
    started = time.time()
    interval = args.interval
    while True:
        status, run = _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
        if status != 200:
            print(json.dumps(run, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        rstatus = run.get("status")
        print(f"[{_now_iso()}] run {run_id} status={rstatus}")
        if rstatus in terminal:
            pr = _pr_url_from_run(run)
            _upsert_state(
                {
                    "id": agent_id,
                    "last_run_id": run_id,
                    "pr_url": pr,
                    "last_run_status": rstatus,
                    "waited_at": _now_iso(),
                }
            )
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 0 if rstatus == "FINISHED" else 1
        elapsed = time.time() - started
        if elapsed >= args.timeout:
            print(f"timeout after {elapsed:.0f}s; cancelling run {run_id}", file=sys.stderr)
            cst, cp = _request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel")
            print(json.dumps({"cancel_status": cst, "cancel": cp}, ensure_ascii=False, indent=2))
            _upsert_state(
                {
                    "id": agent_id,
                    "last_run_id": run_id,
                    "last_run_status": "CANCELLED",
                    "waited_at": _now_iso(),
                }
            )
            return 1
        time.sleep(interval)


def cmd_archive(args: argparse.Namespace) -> int:
    status, payload = _request("POST", f"/v1/agents/{args.id}/archive")
    if status != 200:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    _upsert_state({"id": args.id, "status": "ARCHIVED", "archived_at": _now_iso()})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_me(_: argparse.Namespace) -> int:
    status, payload = _request("GET", "/v1/me")
    if status != 200:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cursor Cloud Agents lifecycle CLI (bank-workshop)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="GET /v1/agents")
    pl.add_argument("--limit", type=int, default=20)
    pl.add_argument("--cursor", default=None)
    pl.add_argument("--include-archived", dest="include_archived", action="store_true", default=None)
    pl.add_argument("--no-include-archived", dest="include_archived", action="store_false")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pg = sub.add_parser("get", help="GET /v1/agents/{id}")
    pg.add_argument("id")
    pg.set_defaults(func=cmd_get)

    pla = sub.add_parser("launch", help="POST /v1/agents (or resume/send if same name active)")
    pla.add_argument("--name", required=True)
    pla.add_argument("--prompt", default=None)
    pla.add_argument("--prompt-file", default=None)
    pla.add_argument("--role", default="author", help="local state role label")
    pla.add_argument("--repo", default=DEFAULT_REPO)
    pla.add_argument("--ref", default=DEFAULT_REF)
    pla.add_argument("--model", default=DEFAULT_MODEL)
    pla.add_argument("--force-new", action="store_true", help="skip resume-by-name")
    pla.set_defaults(func=cmd_launch)

    ps = sub.add_parser("send", help="POST /v1/agents/{id}/runs")
    ps.add_argument("id")
    ps.add_argument("--prompt", default=None)
    ps.add_argument("--prompt-file", default=None)
    ps.set_defaults(func=cmd_send)

    pw = sub.add_parser("wait", help="Poll run until terminal or timeout+cancel")
    pw.add_argument("id")
    pw.add_argument("--run-id", default=None)
    pw.add_argument("--interval", type=int, default=POLL_INTERVAL_SEC)
    pw.add_argument("--timeout", type=int, default=WAIT_TIMEOUT_SEC)
    pw.set_defaults(func=cmd_wait)

    pa = sub.add_parser("archive", help="POST /v1/agents/{id}/archive")
    pa.add_argument("id")
    pa.set_defaults(func=cmd_archive)

    pm = sub.add_parser("me", help="GET /v1/me (sanity)")
    pm.set_defaults(func=cmd_me)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
