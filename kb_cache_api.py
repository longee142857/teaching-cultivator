"""考点小库 HTTP 站点（stdlib，无额外依赖）。

默认监听 0.0.0.0:8765，鉴权：Authorization: Bearer $KB_CACHE_TOKEN
可由 main.py 守护线程启动，或独立运行：
    python kb_cache_api.py
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from learner import kb_cache

DEFAULT_PORT = int(os.environ.get("KB_CACHE_PORT", "8765"))
TOKEN = os.environ.get("KB_CACHE_TOKEN", "")


def _default_host() -> str:
    # 无 token 时只绑本机，避免裸奔；有 token 才对公网开放
    if os.environ.get("KB_CACHE_HOST"):
        return os.environ["KB_CACHE_HOST"]
    return "0.0.0.0" if TOKEN else "127.0.0.1"


DEFAULT_HOST = _default_host()


class Handler(BaseHTTPRequestHandler):
    server_version = "KbCacheAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        # 安静一点，避免刷屏钉钉日志
        if os.environ.get("KB_CACHE_HTTP_VERBOSE") == "1":
            super().log_message(fmt, *args)

    def _auth_ok(self) -> bool:
        if not TOKEN:
            return True  # 未配置 token 时仅建议绑 localhost；云端应设 token
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {TOKEN}":
            return True
        if self.headers.get("X-KB-Token") == TOKEN:
            return True
        return False

    def _json(self, code: int, obj: dict | list) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if path in ("/health", "/v1/health"):
            self._json(200, {"ok": True, **kb_cache.stats()})
            return
        if path == "/v1/stats":
            self._json(200, {"ok": True, **kb_cache.stats()})
            return
        if path == "/v1/queue":
            limit = int((qs.get("limit") or ["50"])[0])
            self._json(200, {"ok": True, "pending": kb_cache.list_pending(limit)})
            return
        if path.startswith("/v1/kb/"):
            parts = path.strip("/").split("/")
            # v1/kb/{subject}/{kp}
            if len(parts) >= 4:
                subject, kp = parts[2], "/".join(parts[3:])
                from urllib.parse import unquote
                subject, kp = unquote(subject), unquote(kp)
                entry = kb_cache.peek(subject, kp)
                if not entry:
                    self._json(404, {"ok": False, "hit": False})
                    return
                self._json(200, {"ok": True, "hit": True, "entry": entry})
                return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        path = urlparse(self.path).path
        data = self._read_json()

        if path == "/v1/kb":
            r = kb_cache.upsert(
                data.get("subject", ""),
                data.get("kp", ""),
                data.get("snippets") or [],
                query=data.get("query") or "",
                request_id=data.get("id") or "",
            )
            self._json(200 if r.get("ok") else 400, r)
            return
        if path == "/v1/fulfill":
            items = data.get("items") or []
            if not isinstance(items, list):
                self._json(400, {"ok": False, "error": "items must be list"})
                return
            r = kb_cache.apply_fulfillments(items)
            self._json(200, {"ok": True, **r})
            return
        if path == "/v1/queue/ack":
            ids = data.get("ids") or []
            n = kb_cache.ack(ids, status=data.get("status") or "done", note=data.get("note") or "")
            self._json(200, {"ok": True, "acked": n})
            return
        if path == "/v1/queue":
            r = kb_cache.enqueue(
                data.get("subject", ""),
                data.get("kp", ""),
                query=data.get("query") or "",
                reason=data.get("reason") or "api",
            )
            self._json(200 if r.get("ok") else 400, r)
            return
        self._json(404, {"ok": False, "error": "not found"})


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def start_in_thread(
    host: str | None = None,
    port: int | None = None,
) -> threading.Thread | None:
    """后台启动；失败返回 None。"""
    if os.environ.get("KB_CACHE_HTTP", "1") != "1":
        return None
    h = host or _default_host()
    p = port if port is not None else DEFAULT_PORT
    try:
        httpd = make_server(h, p)
    except OSError as e:
        print(f"[kb_cache_api] 启动失败: {e}")
        return None

    def _run() -> None:
        print(f"[kb_cache_api] listening http://{h}:{p} token={'yes' if TOKEN else 'no'}")
        httpd.serve_forever()

    t = threading.Thread(target=_run, name="kb-cache-api", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    h = _default_host()
    srv = make_server(h, DEFAULT_PORT)
    print(f"KbCache API on http://{h}:{DEFAULT_PORT}")
    srv.serve_forever()
