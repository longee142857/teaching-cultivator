# -*- coding: utf-8 -*-
"""exam_web unit tests: token / expiry / parse / assemble / deny keys."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
time_mod = __import__("time")
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print("OK", msg)


def sample_md(paper_id: str = "2099-01-01_math") -> str:
    title = "\u53cc\u5468\u68c0\u6d4b\u5377 \u00b7 \u6570\u5b66\u4e00"
    paper = "\u8bd5\u5377"
    subject = "\u79d1\u76ee"
    q = "\u7b2c"
    ti = "\u9898"
    zone = "\u4f5c\u7b54\u533a"
    meta = "\u7b54\u5377\u5143\u4fe1\u606f"
    return (
        f"# {title}\n\n"
        f"- {paper} ID\uff1a`{paper_id}`\n"
        f"- {subject}\uff1amath\n\n"
        f"---\n\n"
        f"## {q} 1 {ti}\uff08compute\uff09\n\n"
        f"Compute $$\\int_0^1 x\\,dx$$.\n\n"
        f"### {zone} 1\n\n"
        f"```\n\n```\n\n"
        f"## {q} 2 {ti}\uff08proof\uff09\n\n"
        f"Prove $a>0$.\n\n"
        f"### {zone} 2\n\n"
        f"```\n\n```\n\n"
        f"---\n\n"
        f"## {meta}\n\n"
        f"- paper_id: {paper_id}\n"
        f"- subject: math\n"
    )


def test_parse_and_assemble():
    from deliver import exam_web as ew

    parsed = ew.parse_public_paper(sample_md())
    check(parsed["paper_id"] == "2099-01-01_math", "parse paper_id")
    check(parsed["n_questions"] == 2, "parse 2 items")
    zone = "\u4f5c\u7b54\u533a"
    check(zone not in parsed["items"][0]["question_md"], "strip answer zone")
    ans_md = ew.assemble_answer_md(
        "2099-01-01_math", {1: "1/2", 2: "proof..."}, subject="math"
    )
    check("paper_id: 2099-01-01_math" in ans_md, "assemble paper_id")
    check("### " + zone + " 1" in ans_md, "assemble zone 1")
    check("1/2" in ans_md, "assemble answer body")


def test_token_expiry(tmp_bank: str):
    os.environ["EXAM_VIEW_SECRET"] = "test-secret"
    os.environ["EXAM_TOKEN_TTL_DAYS"] = "14"
    os.environ["EXAM_WEB_PUBLIC_BASE"] = "https://exam.example.test"

    import importlib
    import config

    importlib.reload(config)
    from learner import biweekly_exam as be

    be.BANK_DIR = tmp_bank
    be.PAPERS_DIR = os.path.join(tmp_bank, "papers")
    be.KEYS_DIR = os.path.join(tmp_bank, "keys")
    be.ANSWERS_DIR = os.path.join(tmp_bank, "answers")
    os.makedirs(be.PAPERS_DIR, exist_ok=True)
    from deliver import exam_web as ew

    importlib.reload(ew)

    tok = ew.issue_token("2099-01-01_math", ttl_days=14)
    check(len(tok) >= 32, "token length")
    check(ew.public_url(tok).startswith("https://exam.example.test/e/"), "public url")
    check(ew.resolve_token(tok)["paper_id"] == "2099-01-01_math", "resolve ok")
    store = ew._load_tokens()
    store[tok]["exp"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat().replace("+00:00", "Z")
    ew._save_tokens(store)
    check(ew.resolve_token(tok) is None, "expired token rejected")


def test_http_deny_and_data(tmp_bank: str):
    from learner import biweekly_exam as be

    be.BANK_DIR = tmp_bank
    be.PAPERS_DIR = os.path.join(tmp_bank, "papers")
    be.KEYS_DIR = os.path.join(tmp_bank, "keys")
    be.ANSWERS_DIR = os.path.join(tmp_bank, "answers")
    os.makedirs(be.PAPERS_DIR, exist_ok=True)
    os.makedirs(be.KEYS_DIR, exist_ok=True)

    pid = "2099-01-02_math"
    with open(os.path.join(be.PAPERS_DIR, f"{pid}.md"), "w", encoding="utf-8") as f:
        f.write(sample_md(pid))
    with open(os.path.join(be.KEYS_DIR, f"{pid}.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"paper_id": pid, "items": [{"i": 1, "answer": "SECRET_ANSWER"}]}, f
        )

    os.environ["EXAM_WEB_HOST"] = "127.0.0.1"
    os.environ["EXAM_WEB_PORT"] = "18766"
    os.environ["EXAM_WEB_PUBLIC_BASE"] = "http://127.0.0.1:18766"
    os.environ["EXAM_VIEW_SECRET"] = "test-secret"
    os.environ["EXAM_SUBMIT_LIMIT_PER_HOUR"] = "5"

    import importlib
    import config

    importlib.reload(config)
    from deliver import exam_web as ew

    importlib.reload(ew)

    tok = ew.issue_token(pid, ttl_days=1)
    httpd = ew.make_server("127.0.0.1", 18766)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time_mod.sleep(0.2)

    def get(path):
        conn = HTTPConnection("127.0.0.1", 18766, timeout=5)
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read()
        status = r.status
        conn.close()
        return status, body

    def post(path, payload):
        conn = HTTPConnection("127.0.0.1", 18766, timeout=5)
        conn.request(
            "POST",
            path,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        r = conn.getresponse()
        body = r.read()
        status = r.status
        conn.close()
        return status, body

    try:
        status, body = get("/health")
        check(status == 200 and json.loads(body).get("ok"), "health")
        status, body = get(f"/e/{tok}/data")
        data = json.loads(body.decode("utf-8"))
        check(status == 200 and data.get("ok"), "data ok")
        check(data["paper"]["paper_id"] == pid, "data paper_id")
        check("SECRET_ANSWER" not in json.dumps(data), "keys never in data")
        for bad in ("/keys/x.json", "/papers/x.md", "/exam_bank/tokens.json"):
            status, _ = get(bad)
            check(status == 404, f"deny {bad}")
        status, _ = get("/e/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/data")
        check(status == 404, "bad token 404")

        import learner.biweekly_exam as be2

        called = {}

        def _fake_submit(md_text, *, paper_id="", user_id=""):
            called["md"] = md_text
            called["paper_id"] = paper_id
            called["user_id"] = user_id
            return "FAKE_REPORT_OK"

        be2.submit_answer_md = _fake_submit
        status, body = post(
            f"/e/{tok}/submit", json.dumps({"answers": {"1": "2"}}).encode()
        )
        out = json.loads(body.decode())
        check(status == 200 and out.get("ok"), "submit ok")
        check(out.get("report") == "FAKE_REPORT_OK", "submit report")
        zone = "\u4f5c\u7b54\u533a"
        check("### " + zone + " 1" in called.get("md", ""), "submit assembled md")
        check(called.get("paper_id") == pid, "submit paper_id")
    finally:
        httpd.shutdown()


def test_action_card_url_builder():
    from deliver.action_cards import build_group_action_param_urls

    key, param = build_group_action_param_urls(
        "paper", "open", [("Open", "https://exam.example.test/e/abc")]
    )
    check(key == "sampleActionCard", "url card key")
    check(param["singleURL"].startswith("https://"), "https singleURL")


def main():
    with tempfile.TemporaryDirectory() as td:
        test_parse_and_assemble()
        test_token_expiry(td)
    with tempfile.TemporaryDirectory() as td:
        test_http_deny_and_data(td)
    test_action_card_url_builder()
    print("ALL PASS")


if __name__ == "__main__":
    main()
