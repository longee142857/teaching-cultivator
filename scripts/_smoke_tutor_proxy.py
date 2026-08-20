# -*- coding: utf-8 -*-
"""Local smoke: mock DSH tutor + practice_web proxy."""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen


class Tutor(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode() or "{}")
        lid = self.headers.get("X-Learner-Id") or body.get("learner")
        out = {
            "ok": True,
            "reply": f"mock tutor ok learner={lid} item={body.get('item')} msg={body.get('message')}",
            "citations": [{"n": 1, "source": "mock", "quote": "smoke"}],
            "detached": False,
        }
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    tutor = HTTPServer(("127.0.0.1", 61900), Tutor)
    threading.Thread(target=tutor.serve_forever, daemon=True).start()

    os.environ["TUTOR_BACKEND_URL"] = "http://127.0.0.1:61900"
    os.environ["PRACTICE_WEB_HTTP"] = "1"
    os.environ["PRACTICE_ALLOW_DEMO_SEED"] = "1"
    os.environ["PRACTICE_GRADE_MODE"] = "ref"
    os.environ["PRACTICE_WEB_PORT"] = "18769"
    os.environ["PRACTICE_WEB_HOST"] = "127.0.0.1"

    from deliver.practice_web import make_server

    httpd = make_server("127.0.0.1", 18769)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)

    def get(path: str):
        with urlopen(f"http://127.0.0.1:18769{path}", timeout=10) as r:
            return r.status, json.loads(r.read().decode())

    def post(path: str, payload: dict, headers: dict | None = None):
        data = json.dumps(payload).encode()
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        req = Request(f"http://127.0.0.1:18769{path}", data=data, headers=h, method="POST")
        with urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())

    checks: list[tuple[str, bool, object]] = []
    st, health = get("/health")
    checks.append(("health", st == 200 and bool(health.get("ok")), health))

    st, boot = get("/api/v1/practice/bootstrap?learner=smoke_demo")
    checks.append(("bootstrap", st == 200 and bool(boot.get("ok") and boot.get("items")), {
        "ok": boot.get("ok"),
        "n_items": len(boot.get("items") or []),
        "tutor": boot.get("tutor"),
    }))

    item = (boot.get("items") or [{}])[0]
    st, tut = post(
        "/api/v1/tutor/chat",
        {
            "learner": "smoke_demo",
            "message": "讲这道题",
            "item": item.get("id"),
            "push": item.get("pushId"),
        },
        {"X-Learner-Id": "smoke_demo"},
    )
    checks.append(
        (
            "tutor_proxy",
            st == 200 and bool(tut.get("ok")) and "mock tutor ok" in (tut.get("reply") or ""),
            tut,
        )
    )

    print("RESULTS")
    ok_all = True
    for name, ok, detail in checks:
        print(("OK" if ok else "FAIL"), name)
        if not ok:
            ok_all = False
            print(" detail", detail)

    httpd.shutdown()
    tutor.shutdown()
    print("SMOKE", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
