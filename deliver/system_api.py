"""教学系统白名单 HTTP API（stdlib，无额外依赖）。

任意 agent（Pi / Cursor / curl）经本机调用；默认仅绑 127.0.0.1。
契约见 docs/system-api.md。

启动：
  - main.py 同进程守护线程（SYSTEM_API_HTTP=1）
  - 或：python -m deliver.system_api
"""
from __future__ import annotations

import inspect
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from agent import tools as T
from learner.context import bind_learner

DEFAULT_PORT = int(os.environ.get("SYSTEM_API_PORT", "8770"))
TOKEN = os.environ.get("SYSTEM_API_TOKEN", "")


def _default_host() -> str:
    if os.environ.get("SYSTEM_API_HOST"):
        return os.environ["SYSTEM_API_HOST"]
    # 无 token 只绑本机；有 token 仍默认本机（公网需显式改 HOST）
    return "127.0.0.1"


DEFAULT_HOST = _default_host()

# 白名单：name -> callable（与 docs/system-api.md / pi-tools-whitelist 对齐）
WHITELIST: dict[str, Callable[..., Any]] = {
    "list_recent_entries": T.list_recent_entries,
    "find_record_entry": T.find_record_entry,
    "get_learner_snapshot": T.get_learner_snapshot,
    "get_active_question": T.get_active_question,
    "list_today_questions": T.list_today_questions,
    "list_knowledge_points": T.list_knowledge_points,
    "kb_query": T.kb_query,
    "list_exam_bank": T.list_exam_bank,
    "get_exam_paper": T.get_exam_paper,
    "get_exam_result": T.get_exam_result,
    "show_solution": T.show_solution,
    "build_report": T.build_report,
    "generate_question": T.generate_question,
    "grade_answer": T.grade_answer,
    "submit_exam_answer_md": T.submit_exam_answer_md,
    "adjust_difficulty": T.adjust_difficulty,
    "note_weak_point": T.note_weak_point,
    "propose_add_kp": T.propose_add_kp,
    "confirm_add_kp": T.confirm_add_kp,
    "cancel_add_kp": T.cancel_add_kp,
    "propose_override_grade": T.propose_override_grade,
    "confirm_override": T.confirm_override,
    "cancel_override": T.cancel_override,
    "kb_enqueue": T.kb_enqueue,
    "write_feedback": T.write_feedback,
    "ocr_handwriting": T.ocr_handwriting,
    "grade_handwriting": T.grade_handwriting,
}

# 模块拆分后：能力参数 / EvidenceBundle（只读）
try:
    from modules.bridge import capability_whitelist

    WHITELIST.update(capability_whitelist())
except Exception:
    pass

# 只读工具：GET 放行；写工具仅 POST（避免 URL 泄露敏感参数）
_READ_TOOLS: set[str] = {
    "list_recent_entries",
    "find_record_entry",
    "get_learner_snapshot",
    "get_active_question",
    "list_today_questions",
    "list_knowledge_points",
    "kb_query",
    "list_exam_bank",
    "get_exam_paper",
    "get_exam_result",
    "show_solution",
    "build_report",
    "get_learner_params",
    "get_capability_evidence",
}


def _tool_schema(name: str, fn: Callable[..., Any]) -> dict:
    sig = inspect.signature(fn)
    params = []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        params.append(
            {
                "name": p.name,
                "required": p.default is inspect.Parameter.empty,
                "default": None if p.default is inspect.Parameter.empty else p.default,
            }
        )
    return {"name": name, "params": params}


def _filter_kwargs(fn: Callable[..., Any], data: dict) -> dict:
    sig = inspect.signature(fn)
    out: dict[str, Any] = {}
    for p in sig.parameters.values():
        if p.name not in data:
            continue
        out[p.name] = data[p.name]
    return out


def call_tool(name: str, learner_id: str, params: dict | None = None) -> dict:
    """供进程内/测试直接调用。"""
    fn = WHITELIST.get(name)
    if not fn:
        return {"ok": False, "error": f"unknown or forbidden tool: {name}"}
    lid = (learner_id or "").strip()
    if not lid:
        return {"ok": False, "error": "missing learner_id (X-Learner-Id)"}
    kwargs = _filter_kwargs(fn, params or {})
    try:
        with bind_learner(lid, binding="personal"):
            result = fn(**kwargs)
        out: dict[str, Any] = {"ok": True, "tool": name, "result": result}
        # get_learner_snapshot：把 ```ability_json 块提升为可解析字段
        if name == "get_learner_snapshot" and isinstance(result, str):
            m = re.search(r"```ability_json\s*\n([\s\S]*?)\n```", result)
            if m:
                try:
                    out["ability"] = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
        return out
    except Exception as e:
        return {"ok": False, "tool": name, "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    server_version = "TeachingSystemAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("SYSTEM_API_VERBOSE") == "1":
            super().log_message(fmt, *args)

    def _auth_ok(self) -> bool:
        if not TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {TOKEN}":
            return True
        if self.headers.get("X-System-Token") == TOKEN:
            return True
        return False

    def _learner_id(self) -> str:
        return (
            self.headers.get("X-Learner-Id")
            or self.headers.get("X-Staff-Id")
            or ""
        ).strip()

    def _json(self, code: int, obj: dict | list) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path in ("/health", "/v1/health"):
            self._json(
                200,
                {
                    "ok": True,
                    "service": "teaching-system-api",
                    "tools": sorted(WHITELIST.keys()),
                },
            )
            return
        if path in ("/v1/tools", "/v1/tools/"):
            self._json(
                200,
                {
                    "ok": True,
                    "tools": [_tool_schema(n, fn) for n, fn in sorted(WHITELIST.items())],
                },
            )
            return
        if path.startswith("/v1/tools/"):
            name = path[len("/v1/tools/") :].strip("/")
            if name not in WHITELIST:
                self._json(404, {"ok": False, "error": "unknown tool"})
                return
            if name not in _READ_TOOLS:
                # 写工具仅 POST；GET 会泄露敏感参数到 URL/日志
                self._json(405, {"ok": False, "error": "use POST for this tool"})
                return
            qs = parse_qs(urlparse(self.path).query)
            params = {k: v[0] for k, v in qs.items() if v}
            # coerce common numerics
            for k in ("days", "num", "limit", "credit"):
                if k in params:
                    try:
                        params[k] = float(params[k]) if "." in params[k] else int(params[k])
                    except ValueError:
                        pass
            for k in ("correct",):
                if k in params:
                    params[k] = str(params[k]).lower() in ("1", "true", "yes")
            r = call_tool(name, self._learner_id(), params)
            self._json(200 if r.get("ok") else 400, r)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        path = urlparse(self.path).path
        data = self._read_json()
        if data is None:
            self._json(400, {"ok": False, "error": "invalid JSON body"})
            return
        if path.startswith("/v1/tools/"):
            name = path[len("/v1/tools/") :].strip("/")
            params = data.get("params") if isinstance(data.get("params"), dict) else data
            r = call_tool(name, self._learner_id() or data.get("learner_id") or "", params)
            self._json(200 if r.get("ok") else 400, r)
            return
        if path == "/v1/call":
            name = (data.get("tool") or data.get("name") or "").strip()
            params = data.get("params") if isinstance(data.get("params"), dict) else {}
            r = call_tool(name, self._learner_id() or data.get("learner_id") or "", params)
            self._json(200 if r.get("ok") else 400, r)
            return
        self._json(404, {"ok": False, "error": "not found"})


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def start_in_thread(
    host: str | None = None,
    port: int | None = None,
) -> threading.Thread | None:
    if os.environ.get("SYSTEM_API_HTTP", "1") != "1":
        return None
    h = host or _default_host()
    p = port if port is not None else DEFAULT_PORT
    try:
        httpd = make_server(h, p)
    except OSError as e:
        print(f"[system_api] 启动失败: {e}")
        return None

    def _run() -> None:
        print(f"[system_api] listening http://{h}:{p} tools={len(WHITELIST)} token={'yes' if TOKEN else 'no'}")
        httpd.serve_forever()

    t = threading.Thread(target=_run, name="teaching-system-api", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    h = _default_host()
    srv = make_server(h, DEFAULT_PORT)
    print(f"Teaching System API on http://{h}:{DEFAULT_PORT}")
    srv.serve_forever()
