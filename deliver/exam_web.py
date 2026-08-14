# -*- coding: utf-8 -*-
"""Biweekly exam H5 viewer (KaTeX) -- stdlib HTTP, bind localhost only.

Routes (nginx TLS reverse-proxy to public):
  GET  /e/{token}          -> HTML shell
  GET  /e/{token}/data     -> paper JSON (parsed from public md; never keys)
  POST /e/{token}/submit   -> assemble answer md -> submit_answer_md
  GET  /health             -> healthcheck

Token: random hex stored in data/exam_bank/tokens.json; lazy expiry purge.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Chinese literals via escapes so file encoding cannot corrupt regexes.
_U_PAPER = "\u8bd5\u5377"  # ÊÔ¾í
_U_SUBJECT = "\u79d1\u76ee"  # ¿ÆÄ¿
_U_TITLE = "\u53cc\u5468\u68c0\u6d4b\u5377"  # Ë«ÖÜ¼ì²â¾í
_U_Q = "\u7b2c"  # µÚ
_U_TI = "\u9898"  # Ìâ
_U_ANS_ZONE = "\u4f5c\u7b54\u533a"  # ×÷´ðÇø
_U_META = "\u7b54\u5377\u5143\u4fe1\u606f"  # ´ð¾íÔªÐÅÏ¢
_U_BIWEEKLY_ANS = "\u53cc\u5468\u7b54\u5377"  # Ë«ÖÜ´ð¾í

_TOKEN_RE = re.compile(r"^[a-f0-9]{32,64}$")
_PID_LINE_RE = re.compile(_U_PAPER + r"\s*ID[\uFF1A:]\s*`?([A-Za-z0-9_\-]+)`?")
_SUBJ_LINE_RE = re.compile(_U_SUBJECT + r"[\uFF1A:]\s*([^\n]+)")
_TITLE_RE = re.compile(
    r"^#\s*" + _U_TITLE + r"\s*[\u00B7\u2022]\s*(.+)\s*$", re.MULTILINE
)
_ITEM_RE = re.compile(
    r"##\s*"
    + _U_Q
    + r"\s*(\d+)\s*"
    + _U_TI
    + r"[\uFF08(]?([^\uFF09)\n]*)[\uFF09)]?\s*\n([\s\S]*?)(?=##\s*"
    + _U_Q
    + r"\s*\d+\s*"
    + _U_TI
    + r"|##\s*"
    + _U_META
    + r"|$)"
)
_ANS_ZONE_TAIL_RE = re.compile(r"###\s*" + _U_ANS_ZONE + r"[\s\S]*$")

_lock = threading.Lock()
_rate: dict[str, list[float]] = {}


def _cfg():
    from config import (
        DATA_DIR,
        EXAM_SUBMIT_LIMIT_PER_HOUR,
        EXAM_TOKEN_TTL_DAYS,
        EXAM_VIEW_SECRET,
        EXAM_WEB_HOST,
        EXAM_WEB_PORT,
        EXAM_WEB_PUBLIC_BASE,
    )

    return {
        "data_dir": DATA_DIR,
        "secret": EXAM_VIEW_SECRET or "",
        "ttl_days": max(1, int(EXAM_TOKEN_TTL_DAYS)),
        "public_base": (EXAM_WEB_PUBLIC_BASE or "").rstrip("/"),
        "host": EXAM_WEB_HOST or "127.0.0.1",
        "port": int(EXAM_WEB_PORT),
        "submit_limit": max(1, int(EXAM_SUBMIT_LIMIT_PER_HOUR)),
    }


def tokens_path() -> str:
    from learner.biweekly_exam import BANK_DIR

    return os.path.join(BANK_DIR, "tokens.json")


def drafts_dir() -> str:
    from learner.biweekly_exam import BANK_DIR

    return os.path.join(BANK_DIR, "drafts")


def _draft_path(paper_id: str, uid: str) -> str:
    uid = re.sub(r"[^A-Za-z0-9_\-]", "", uid or "")[:64]
    if not uid:
        uid = "anonymous"
    return os.path.join(drafts_dir(), f"{paper_id}_{uid}.json")


def save_draft(paper_id: str, uid: str, answers: dict) -> bool:
    """保存某人对某卷的草稿（防抖由前端做）。"""
    if not paper_id or not isinstance(answers, dict):
        return False
    path = _draft_path(paper_id, uid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {
                "paper_id": paper_id,
                "uid": uid,
                "answers": answers,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    os.replace(tmp, path)
    return True


def load_draft(paper_id: str, uid: str) -> dict:
    path = _draft_path(paper_id, uid)
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("answers"), dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def clear_draft(paper_id: str, uid: str) -> None:
    path = _draft_path(paper_id, uid)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _exchange_auth_code(auth_code: str) -> str:
    """钉钉免登 authCode → staffId；失败返回空串（前端降级设备 UUID）。"""
    import requests
    from config import DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET
    from deliver.dingtalk_media import get_access_token

    code = (auth_code or "").strip()
    if not code:
        return ""
    try:
        token = get_access_token(DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET)
        if not token:
            return ""
        r = requests.post(
            "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo",
            params={"access_token": token},
            json={"code": code},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errcode") == 0:
            return (data.get("result") or {}).get("userid") or ""
    except Exception:
        logger.exception("auth code exchange failed")
    return ""


def static_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "static")


def _load_tokens() -> dict:
    path = tokens_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_tokens(data: dict) -> None:
    from learner.biweekly_exam import BANK_DIR

    os.makedirs(BANK_DIR, exist_ok=True)
    path = tokens_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _purge_expired(store: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {}
    for tok, meta in store.items():
        if not isinstance(meta, dict):
            continue
        exp = (meta.get("exp") or "").strip()
        if not exp:
            continue
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if exp_dt > now:
            out[tok] = meta
    return out


def issue_token(paper_id: str, *, ttl_days: int | None = None) -> str:
    """Issue random token and persist; return token string."""
    cfg = _cfg()
    days = ttl_days if ttl_days is not None else cfg["ttl_days"]
    pid = (paper_id or "").strip()
    if not pid:
        raise ValueError("paper_id required")
    if not cfg["secret"]:
        logger.warning("EXAM_VIEW_SECRET empty -- tokens still random, set secret in prod")

    token = secrets.token_hex(24)
    exp = datetime.now(timezone.utc) + timedelta(days=days)
    with _lock:
        store = _purge_expired(_load_tokens())
        store[token] = {
            "paper_id": pid,
            "exp": exp.isoformat().replace("+00:00", "Z"),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _save_tokens(store)
    return token


def public_url(token: str) -> str:
    base = _cfg()["public_base"]
    if not base:
        return f"/e/{token}"
    return f"{base}/e/{token}"


def issue_exam_url(paper_id: str) -> str | None:
    if not paper_id:
        return None
    tok = issue_token(paper_id)
    return public_url(tok)


def resolve_token(token: str) -> dict | None:
    """Validate token -> {paper_id, exp, token}; None if invalid/expired."""
    tok = (token or "").strip().lower()
    if not _TOKEN_RE.match(tok):
        return None
    with _lock:
        store = _purge_expired(_load_tokens())
        meta = store.get(tok)
        _save_tokens(store)
        if not meta:
            return None
        return {"token": tok, "paper_id": meta["paper_id"], "exp": meta.get("exp", "")}


def read_public_md(paper_id: str) -> str:
    from learner.biweekly_exam import PAPERS_DIR

    path = os.path.join(PAPERS_DIR, f"{paper_id}.md")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse_public_paper(md: str) -> dict[str, Any]:
    """Parse public md into question stems (no answer keys)."""
    title = ""
    m = _TITLE_RE.search(md or "")
    if m:
        title = m.group(1).strip()
    paper_id = ""
    m2 = _PID_LINE_RE.search(md or "")
    if m2:
        paper_id = m2.group(1).strip()
    subject = ""
    m3 = _SUBJ_LINE_RE.search(md or "")
    if m3:
        subject = m3.group(1).strip()

    items = []
    for m in _ITEM_RE.finditer(md or ""):
        i = int(m.group(1))
        form_label = (m.group(2) or "").strip()
        body = m.group(3) or ""
        body = _ANS_ZONE_TAIL_RE.sub("", body).strip()
        items.append({"i": i, "form_label": form_label, "question_md": body})
    items.sort(key=lambda x: x["i"])
    return {
        "paper_id": paper_id,
        "title": title or paper_id,
        "subject": subject,
        "items": items,
        "n_questions": len(items),
    }


def assemble_answer_md(
    paper_id: str, answers: dict[str | int, str], subject: str = ""
) -> str:
    lines = [f"# {_U_BIWEEKLY_ANS} ¡¤ `{paper_id}`", "", f"- paper_id: {paper_id}"]
    if subject:
        lines.append(f"- subject: {subject}")
    lines.append("")
    keys = sorted(int(k) for k in answers.keys())
    for i in keys:
        ua = (answers.get(i) or answers.get(str(i)) or "").strip()
        lines.append(f"### {_U_ANS_ZONE} {i}")
        lines.append("")
        lines.append("```")
        lines.append(ua)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def check_rate_limit(token: str) -> bool:
    limit = _cfg()["submit_limit"]
    now = time.time()
    window = 3600.0
    with _lock:
        hits = [t for t in _rate.get(token, []) if now - t < window]
        if len(hits) >= limit:
            _rate[token] = hits
            return False
        hits.append(now)
        _rate[token] = hits
        return True


def paper_payload(paper_id: str) -> dict | None:
    md = read_public_md(paper_id)
    if not md:
        return None
    parsed = parse_public_paper(md)
    if not parsed.get("paper_id"):
        parsed["paper_id"] = paper_id
    return parsed


def _html_shell() -> bytes:
    path = os.path.join(static_dir(), "exam.html")
    with open(path, "rb") as f:
        return f.read()


class ExamHandler(BaseHTTPRequestHandler):
    server_version = "ExamWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("EXAM_WEB_VERBOSE") == "1":
            super().log_message(fmt, *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj: dict | list) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            logger.warning("exam_web client disconnected during JSON write")

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _parse_e_path(self) -> tuple[str, str] | None:
        path = unquote(urlparse(self.path).path)
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts or parts[0] != "e" or len(parts) < 2:
            return None
        token = parts[1].lower()
        action = parts[2] if len(parts) >= 3 else ""
        if len(parts) > 3:
            return None
        return token, action

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/e/health"):
            self._json(200, {"ok": True, "service": "exam_web"})
            return

        if path.startswith("/static/"):
            name = path[len("/static/") :]
            if ".." in name or name.startswith("/") or not name:
                self._json(404, {"ok": False, "error": "not found"})
                return
            fpath = os.path.join(static_dir(), name)
            if not os.path.isfile(fpath):
                self._json(404, {"ok": False, "error": "not found"})
                return
            ctype = "application/octet-stream"
            if name.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif name.endswith(".js"):
                ctype = "application/javascript; charset=utf-8"
            elif name.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            elif name.endswith(".woff2"):
                ctype = "font/woff2"
            elif name.endswith(".woff"):
                ctype = "font/woff"
            elif name.endswith(".ttf"):
                ctype = "font/ttf"
            with open(fpath, "rb") as f:
                self._bytes(200, f.read(), ctype)
            return

        if "/keys/" in path or path.startswith("/papers") or "exam_bank" in path:
            self._json(404, {"ok": False, "error": "not found"})
            return

        parsed = self._parse_e_path()
        if not parsed:
            self._json(404, {"ok": False, "error": "not found"})
            return
        token, action = parsed
        meta = resolve_token(token)
        if not meta:
            self._json(404, {"ok": False, "error": "invalid or expired token"})
            return

        if action == "":
            try:
                self._bytes(200, _html_shell(), "text/html; charset=utf-8")
            except OSError as e:
                self._json(500, {"ok": False, "error": f"missing exam.html: {e}"})
            return

        if action == "data":
            payload = paper_payload(meta["paper_id"])
            if not payload:
                self._json(404, {"ok": False, "error": "paper not found"})
                return
            from config import DINGTALK_CORP_ID
            self._json(200, {
                "ok": True,
                "paper": payload,
                "exp": meta.get("exp", ""),
                "corp_id": DINGTALK_CORP_ID or "",
            })
            return

        if action == "draft":
            from urllib.parse import parse_qs
            uid = (parse_qs(urlparse(self.path).query).get("uid") or [""])[0]
            if not uid:
                self._json(400, {"ok": False, "error": "missing uid"})
                return
            d = load_draft(meta["paper_id"], uid)
            self._json(200, {"ok": True, "answers": d.get("answers") or {}})
            return

        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = self._parse_e_path()
        if not parsed:
            self._json(404, {"ok": False, "error": "not found"})
            return
        token, action = parsed

        if action == "identify":
            meta = resolve_token(token)
            if not meta:
                self._json(404, {"ok": False, "error": "invalid or expired token"})
                return
            data = self._read_json()
            auth_code = (data.get("authCode") or "").strip()
            if not auth_code:
                self._json(400, {"ok": False, "error": "missing authCode"})
                return
            uid = _exchange_auth_code(auth_code)
            if uid:
                self._json(200, {"ok": True, "uid": uid, "fallback": False})
            else:
                self._json(200, {"ok": False, "fallback": True,
                                 "error": "auth exchange failed"})
            return

        if action == "draft":
            meta = resolve_token(token)
            if not meta:
                self._json(404, {"ok": False, "error": "invalid or expired token"})
                return
            data = self._read_json()
            uid = (data.get("uid") or "").strip()
            answers = data.get("answers")
            if not uid or not isinstance(answers, dict):
                self._json(400, {"ok": False, "error": "uid/answers required"})
                return
            save_draft(meta["paper_id"], uid, answers)
            self._json(200, {"ok": True})
            return

        if action != "submit":
            self._json(404, {"ok": False, "error": "not found"})
            return

        meta = resolve_token(token)
        if not meta:
            self._json(404, {"ok": False, "error": "invalid or expired token"})
            return

        if not check_rate_limit(token):
            self._json(
                429,
                {
                    "ok": False,
                    "error": "\u63d0\u4ea4\u8fc7\u4e8e\u9891\u7e41\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5",
                },
            )
            return

        data = self._read_json()
        raw_answers = data.get("answers") or {}
        uid = (data.get("uid") or "").strip()
        try:
            from learner.roster import resolve_exam_uid
            uid = resolve_exam_uid(uid) if uid else uid
        except Exception:
            pass
        if not isinstance(raw_answers, dict):
            self._json(400, {"ok": False, "error": "answers must be object"})
            return
        answers: dict[int, str] = {}
        for k, v in raw_answers.items():
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            answers[i] = "" if v is None else str(v)

        if not any((a or "").strip() for a in answers.values()):
            self._json(
                400,
                {
                    "ok": False,
                    "error": "\u8bf7\u81f3\u5c11\u586b\u5199\u4e00\u9898\u518d\u63d0\u4ea4",
                },
            )
            return

        paper = paper_payload(meta["paper_id"]) or {}
        md = assemble_answer_md(
            meta["paper_id"],
            answers,
            subject=paper.get("subject") or "",
        )
        try:
            from learner.biweekly_exam import submit_answer_md
            from learner.context import bind_learner

            # \u7f51\u9875\u63d0\u4ea4\uff1a\u7ed1\u5b9a\u8bc6\u522b\u5230\u7684\u5b66\u5458\u8eab\u4efd\uff0c\u6279\u6539/BKT \u843d\u5230\u8be5\u5b66\u5458\u540d\u4e0b
            if uid:
                with bind_learner(uid, binding="personal"):
                    report = submit_answer_md(
                        md, paper_id=meta["paper_id"], user_id=uid
                    )
            else:
                report = submit_answer_md(md, paper_id=meta["paper_id"])
            clear_draft(meta["paper_id"], uid or "anonymous")
            raw_uid = (data.get("uid") or "").strip()
            if raw_uid and raw_uid != uid:
                clear_draft(meta["paper_id"], raw_uid)
        except Exception as e:
            logger.exception("exam submit failed")
            self._json(
                500,
                {
                    "ok": False,
                    "error": "\u6279\u6539\u5931\u8d25: " + str(e),
                },
            )
            return

        self._json(200, {"ok": True, "report": (report or "")[:8000]})


def make_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    cfg = _cfg()
    h = host or cfg["host"]
    p = port if port is not None else cfg["port"]
    return ThreadingHTTPServer((h, p), ExamHandler)


def start_in_thread(
    host: str | None = None,
    port: int | None = None,
) -> threading.Thread | None:
    from config import EXAM_WEB_HTTP

    if not EXAM_WEB_HTTP:
        return None
    cfg = _cfg()
    h = host or cfg["host"]
    p = port if port is not None else cfg["port"]
    try:
        httpd = make_server(h, p)
    except OSError as e:
        logger.warning("exam_web start failed: %s", e)
        print(f"[exam_web] start failed: {e}")
        return None

    def _run() -> None:
        print(
            f"[exam_web] listening http://{h}:{p} "
            f"base={cfg['public_base'] or '(relative)'}"
        )
        httpd.serve_forever()

    t = threading.Thread(target=_run, name="exam-web", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    cfg = _cfg()
    httpd = make_server()
    print(f"[exam_web] http://{cfg['host']}:{cfg['port']}")
    httpd.serve_forever()
