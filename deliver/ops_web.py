# -*- coding: utf-8 -*-
"""Ops monitor board — readonly rejects + learner params (stdlib HTTP).

Routes (nginx reverse-proxy /ops/ -> 127.0.0.1:8767):
  GET /ops/              -> HTML
  GET /ops/api/rejects   -> ?date=YYYY-MM-DD
  GET /ops/api/learners  -> roster snapshot
  GET /ops/api/status    -> heartbeat / last_class / today count
  GET /ops/health        -> healthcheck

Auth: OPS_VIEW_TOKEN via ?token= or header X-Ops-Token.
If token empty in env, bind stays localhost-only (no public auth needed).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

_server: ThreadingHTTPServer | None = None


def _cfg() -> dict[str, Any]:
    from config import (
        DATA_DIR,
        OPS_VIEW_TOKEN,
        OPS_WEB_HOST,
        OPS_WEB_HTTP,
        OPS_WEB_PORT,
    )

    return {
        "data_dir": DATA_DIR,
        "host": OPS_WEB_HOST or "127.0.0.1",
        "port": int(OPS_WEB_PORT),
        "token": (OPS_VIEW_TOKEN or "").strip(),
        "enabled": bool(OPS_WEB_HTTP),
    }


def static_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "static")


def rejects_path() -> str:
    return os.path.join(_cfg()["data_dir"], "ops", "rejects.jsonl")


def _read_json(path: str) -> Any:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def load_rejects(date: str | None = None, limit: int = 200) -> list[dict]:
    path = rejects_path()
    if not os.path.isfile(path):
        return []
    want = (date or datetime.date.today().isoformat()).strip()
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                ts = str(obj.get("ts") or "")
                if ts.startswith(want) or (obj.get("date") == want):
                    rows.append(obj)
    except OSError:
        return []
    return rows[-max(1, min(limit, 500)) :]


def load_learners() -> list[dict]:
    from learner import paths as P

    root = P.learners_root()
    if not os.path.isdir(root):
        return []
    out: list[dict] = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        diff = _read_json(os.path.join(d, "difficulty.json")) or {}
        blocks = _read_json(os.path.join(d, "memory_blocks.json")) or {}
        weights = _read_json(os.path.join(d, "weights.json")) or {}
        aq = (blocks.get("active_question") or {}) if isinstance(blocks, dict) else {}
        sess = (blocks.get("session") or {}) if isinstance(blocks, dict) else {}
        digest = ""
        if isinstance(blocks, dict):
            digest = str(blocks.get("learner_digest") or "")[:400]
        # weights TOP (flat-ish)
        top: list[dict] = []
        if isinstance(weights, dict):
            flat: list[tuple[str, float]] = []
            for subj, tree in weights.items():
                if not isinstance(tree, dict):
                    continue
                for k, v in tree.items():
                    if isinstance(v, (int, float)):
                        flat.append((f"{subj}/{k}", float(v)))
                    elif isinstance(v, dict):
                        for k2, v2 in v.items():
                            if isinstance(v2, (int, float)):
                                flat.append((f"{subj}/{k}/{k2}", float(v2)))
            flat.sort(key=lambda x: -x[1])
            top = [{"kp": k, "w": round(w, 4)} for k, w in flat[:8]]
        out.append(
            {
                "staff_id": name,
                "difficulty": diff if isinstance(diff, dict) else {},
                "phase": sess.get("phase") if isinstance(sess, dict) else "",
                "active_question": {
                    "subject": aq.get("subject") or "",
                    "kp": aq.get("kp") or "",
                    "preview": (aq.get("preview") or "")[:180],
                    "char_len": aq.get("char_len") or 0,
                    "source": aq.get("source") or "",
                },
                "weights_top": top,
                "digest_head": digest,
            }
        )
    return out


def load_status() -> dict:
    from config import DAILY_RECORD_DIR
    from learner import paths as P

    today = datetime.date.today().isoformat()
    today_count = 0
    try:
        from record_index import count_today_entries

        today_count = count_today_entries(DAILY_RECORD_DIR, today)
    except Exception:
        pass
    pub = _read_json(P.public_last_class_path()) or {}
    rejects_today = load_rejects(today)
    n_reject = sum(1 for r in rejects_today if r.get("kind") == "reject")
    n_bypass = sum(1 for r in rejects_today if r.get("kind") == "review_parse_bypassed")
    return {
        "ok": True,
        "today": today,
        "today_entry_count": today_count,
        "rejects_today": n_reject,
        "parse_bypass_today": n_bypass,
        "last_class": {
            "subject": pub.get("subject") or "",
            "kp": pub.get("kp") or "",
            "timestamp": pub.get("timestamp") or "",
            "q_len": len(pub.get("question") or ""),
            "preview": " ".join(((pub.get("question") or "").split()))[:160],
        },
        "rejects_path": rejects_path(),
    }


def _html_shell() -> bytes:
    path = os.path.join(static_dir(), "ops.html")
    with open(path, "rb") as f:
        return f.read()


class OpsHandler(BaseHTTPRequestHandler):
    server_version = "OpsWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("OPS_WEB_VERBOSE") == "1":
            super().log_message(fmt, *args)

    def _json(self, code: int, obj: dict | list) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        cfg = _cfg()
        expected = cfg["token"]
        if not expected:
            # No token configured: only safe when bound to localhost
            return True
        qs = parse_qs(urlparse(self.path).query)
        tok = (qs.get("token") or [""])[0].strip()
        if not tok:
            tok = (self.headers.get("X-Ops-Token") or "").strip()
        return tok == expected and bool(tok)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        # normalize trailing slash variants
        if path.endswith("/") and path != "/":
            path_noslash = path.rstrip("/")
        else:
            path_noslash = path

        if path_noslash in ("/ops/health", "/health"):
            self._json(200, {"ok": True, "service": "ops_web"})
            return

        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        if path_noslash in ("/ops", "/ops/"):
            try:
                self._bytes(200, _html_shell(), "text/html; charset=utf-8")
            except OSError as e:
                self._json(500, {"ok": False, "error": f"missing ops.html: {e}"})
            return

        if path_noslash == "/ops/api/rejects":
            qs = parse_qs(parsed.query)
            date = (qs.get("date") or [""])[0].strip() or None
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            rows = load_rejects(date, limit=limit)
            self._json(200, {"ok": True, "date": date or datetime.date.today().isoformat(), "rows": rows})
            return

        if path_noslash == "/ops/api/learners":
            self._json(200, {"ok": True, "learners": load_learners()})
            return

        if path_noslash == "/ops/api/status":
            self._json(200, load_status())
            return

        self._json(404, {"ok": False, "error": "not found"})


def make_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    cfg = _cfg()
    h = host or cfg["host"]
    p = port if port is not None else cfg["port"]
    httpd = ThreadingHTTPServer((h, p), OpsHandler)
    return httpd


def start_in_thread(
    host: str | None = None,
    port: int | None = None,
) -> threading.Thread | None:
    global _server
    cfg = _cfg()
    if not cfg["enabled"]:
        return None
    h = host or cfg["host"]
    p = port if port is not None else cfg["port"]
    try:
        httpd = make_server(h, p)
    except OSError as e:
        logger.warning("ops_web start failed: %s", e)
        print(f"[ops_web] start failed: {e}")
        return None
    _server = httpd

    def _run() -> None:
        tok = "set" if cfg["token"] else "empty(localhost-only)"
        print(f"[ops_web] listening http://{h}:{p}/ops/ token={tok}")
        httpd.serve_forever()

    t = threading.Thread(target=_run, name="ops-web", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    cfg = _cfg()
    httpd = make_server()
    print(f"[ops_web] http://{cfg['host']}:{cfg['port']}/ops/")
    httpd.serve_forever()
