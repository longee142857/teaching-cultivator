# -*- coding: utf-8 -*-
"""Practice desk HTTP — teaching-shell + JSON API (stdlib).

Routes (nginx may reverse-proxy /practice/ -> :8768):
  GET  /                 -> redirect /practice
  GET  /practice          -> teaching-shell.html
  GET  /health           -> healthcheck
  GET  /api/v1/agent/manifest
  GET  /api/v1/practice/bootstrap?learner=
  GET  /api/v1/practice/item?learner=&item=&push=
  GET  /api/v1/practice/params?learner=
  POST /api/v1/practice/submit
  POST /api/v1/tutor/chat          -> proxy TUTOR_BACKEND_URL or 501 stub

Auth: PRACTICE_API_TOKEN via Bearer / X-Practice-Token / ?token=
      (empty token → localhost-only trust, same as ops/exam)

Tutor: set TUTOR_BACKEND_URL (e.g. http://127.0.0.1:61900) to proxy
      POST /api/v1/tutor/chat to DSH mentor-team host; unset → 501.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

_server: ThreadingHTTPServer | None = None


def _tutor_backend_url() -> str:
    try:
        from config import TUTOR_BACKEND_URL

        return (TUTOR_BACKEND_URL or "").strip().rstrip("/")
    except Exception:
        return (os.environ.get("TUTOR_BACKEND_URL") or "").strip().rstrip("/")


def _proxy_tutor_chat(payload: dict[str, Any], learner: str) -> tuple[int, dict[str, Any]]:
    """Forward tutor chat to DSH mentor-team. Returns (status, body)."""
    base = _tutor_backend_url()
    if not base:
        return 0, {}
    body = dict(payload or {})
    if learner and not (body.get("learner") or body.get("learner_id")):
        body["learner"] = learner
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if learner:
        headers["X-Learner-Id"] = learner
    req = urllib.request.Request(
        f"{base}/api/v1/tutor/chat",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                out = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                out = {"ok": False, "error": "tutor_backend_bad_json", "raw": raw[:500]}
            if not isinstance(out, dict):
                out = {"ok": False, "error": "tutor_backend_bad_shape", "raw": out}
            return int(getattr(resp, "status", 200) or 200), out
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            out = json.loads(raw) if raw else {"ok": False, "error": "tutor_backend_http_error"}
        except json.JSONDecodeError:
            out = {"ok": False, "error": "tutor_backend_http_error", "detail": raw[:500]}
        if not isinstance(out, dict):
            out = {"ok": False, "error": "tutor_backend_http_error"}
        out.setdefault("ok", False)
        return int(e.code or 502), out
    except Exception as e:
        logger.warning("tutor backend unreachable: %s", e)
        return 502, {
            "ok": False,
            "error": "tutor_backend_unreachable",
            "detail": str(e)[:300],
            "backend": base,
        }


def _cfg() -> dict[str, Any]:
    try:
        from config import (
            PRACTICE_API_TOKEN,
            PRACTICE_WEB_HOST,
            PRACTICE_WEB_HTTP,
            PRACTICE_WEB_PORT,
        )

        return {
            "host": PRACTICE_WEB_HOST or "127.0.0.1",
            "port": int(PRACTICE_WEB_PORT),
            "token": (PRACTICE_API_TOKEN or "").strip(),
            "enabled": bool(PRACTICE_WEB_HTTP),
        }
    except Exception:
        return {
            "host": os.environ.get("PRACTICE_WEB_HOST", "127.0.0.1"),            "port": int(os.environ.get("PRACTICE_WEB_PORT", "8768")),
            "token": (os.environ.get("PRACTICE_API_TOKEN") or "").strip(),
            "enabled": os.environ.get("PRACTICE_WEB_HTTP", "1") == "1",
        }


def static_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "static")


def shell_path() -> str:
    return os.path.join(static_dir(), "teaching-shell.html")


class PracticeHandler(BaseHTTPRequestHandler):
    server_version = "TeachingPractice/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("PRACTICE_WEB_VERBOSE") == "1":
            super().log_message(fmt, *args)

    def _cors(self) -> None:
        origin = os.environ.get("PRACTICE_CORS_ORIGIN", "").strip()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Practice-Token, X-Learner-Id")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        expected = _cfg()["token"]
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {expected}":
            return True
        tok = (self.headers.get("X-Practice-Token") or "").strip()
        if tok == expected:
            return True
        qs = parse_qs(urlparse(self.path).query)
        tok = (qs.get("token") or [""])[0].strip()
        return tok == expected and bool(tok)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 2_000_000))
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return obj if isinstance(obj, dict) else {}

    def _learner(self, qs: dict, body: dict | None = None) -> str:
        body = body or {}
        for key in ("learner", "learner_id", "user_id"):
            v = (body.get(key) or "").strip() if isinstance(body.get(key), str) else ""
            if v:
                return v
            v = (qs.get(key) or [""])[0].strip()
            if v:
                return v
        return (self.headers.get("X-Learner-Id") or self.headers.get("X-Staff-Id") or "").strip()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path in ("/health", "/practice/health"):
            self._json(200, {"ok": True, "service": "practice_web"})
            return

        if path in ("/", "/practice/", "/p"):
            self.send_response(302)
            self.send_header("Location", "/practice")
            self._cors()
            self.end_headers()
            return

        if path == "/practice":
            try:
                with open(shell_path(), "rb") as f:
                    html = f.read()
                self._bytes(200, html, "text/html; charset=utf-8")
            except OSError as e:
                self._json(500, {"ok": False, "error": f"missing teaching-shell.html: {e}"})
            return

        if path in ("/capability-brain.html", "/capability-brain"):
            fp = os.path.join(static_dir(), "capability-brain.html")
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    self._bytes(200, f.read(), "text/html; charset=utf-8")
                return
            self._json(404, {"ok": False, "error": "capability-brain.html missing"})
            return

        # /assets/* (brain) and /static/* (katex etc.)
        if path.startswith("/assets/") or path.startswith("/static/"):
            prefix = "/assets/" if path.startswith("/assets/") else "/static/"
            rel = path[len(prefix) :].replace("..", "")
            if path.startswith("/assets/"):
                fp = os.path.join(static_dir(), "assets", rel)
            else:
                fp = os.path.join(static_dir(), rel)
            if os.path.isfile(fp):
                ctype = "application/octet-stream"
                if fp.endswith(".js"):
                    ctype = "application/javascript; charset=utf-8"
                elif fp.endswith(".css"):
                    ctype = "text/css; charset=utf-8"
                elif fp.endswith(".html"):
                    ctype = "text/html; charset=utf-8"
                with open(fp, "rb") as f:
                    self._bytes(200, f.read(), ctype)
                return
            self._json(404, {"ok": False, "error": "not found"})
            return

        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        from modules.bridge import practice_service as ps

        if path == "/api/v1/agent/manifest":
            self._json(200, {"ok": True, "manifest": ps.agent_manifest()})
            return

        if path == "/api/v1/practice/bootstrap":
            lid = self._learner(qs)
            day = (qs.get("day") or [""])[0].strip() or None
            self._json(200 if lid else 400, ps.bootstrap(lid, day=day))
            return

        if path == "/api/v1/practice/item":
            lid = self._learner(qs)
            item = (qs.get("item") or [""])[0].strip() or None
            push = (qs.get("push") or [""])[0].strip() or None
            out = ps.get_item(lid, item=item, push=push)
            self._json(200 if out.get("ok") else 404, out)
            return

        if path == "/api/v1/practice/params":
            lid = self._learner(qs)
            out = ps.get_params(lid)
            self._json(200 if out.get("ok") else 400, out)
            return

        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")

        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        body = self._read_json()
        qs = parse_qs(parsed.query)
        from modules.bridge import practice_service as ps

        if path == "/api/v1/practice/submit":
            lid = self._learner(qs, body)
            out = ps.submit(
                lid,
                answer=str(body.get("answer") or body.get("user_answer") or ""),
                item=body.get("item") or body.get("item_id"),
                push=body.get("push") or body.get("push_id"),
                mode=str(body.get("mode") or "") or None,
            )
            code = 200 if out.get("ok") else 400
            self._json(code, out)
            return

        if path == "/api/v1/tutor/chat":
            lid = self._learner(qs, body)
            if _tutor_backend_url():
                code, out = _proxy_tutor_chat(body, lid)
                self._json(code or 502, out)
                return
            self._json(
                501,
                {
                    "ok": False,
                    "error": "tutor_agent_not_wired",
                    "hint": "Set TUTOR_BACKEND_URL to DSH mentor-team (see integrations/dsh-mentor-team/wiring.md)",
                    "contract": ps.agent_manifest()["tutor"]["chat"],
                    "echo": {
                        "learner": lid,
                        "item": body.get("item"),
                        "push": body.get("push"),
                        "message": body.get("message") or body.get("text"),
                    },
                },
            )
            return

        self._json(404, {"ok": False, "error": "not found"})


def make_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    cfg = _cfg()
    h = host or cfg["host"]
    p = port if port is not None else cfg["port"]
    return ThreadingHTTPServer((h, p), PracticeHandler)


def start_in_thread(
    host: str | None = None,
    port: int | None = None,
) -> threading.Thread | None:
    global _server
    cfg = _cfg()
    if not cfg["enabled"]:
        return None
    try:
        httpd = make_server(host, port)
    except OSError as e:
        logger.warning("practice_web bind failed: %s", e)
        return None
    _server = httpd

    def _run() -> None:
        logger.info(
            "practice_web on http://%s:%s/practice",
            httpd.server_address[0],
            httpd.server_address[1],
        )
        httpd.serve_forever(poll_interval=0.5)

    t = threading.Thread(target=_run, name="practice_web", daemon=True)
    t.start()
    return t


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    httpd = make_server()
    print(f"practice_web http://{httpd.server_address[0]}:{httpd.server_address[1]}/practice")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
