# -*- coding: utf-8 -*-
"""Practice desk API + DTO smoke (no LLM)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print("OK", msg)


def test_dto():
    from modules.bridge.practice_dto import (
        extract_katex,
        parse_item_id,
        public_item_id,
        push_to_shell_item,
    )

    check(public_item_id(12) == "i12", "public id")
    check(parse_item_id("i12") == 12, "parse i12")
    check(parse_item_id("12") == 12, "parse 12")
    katex = extract_katex(r"stem $$\lim x$$ tail")
    check("lim" in katex, "extract katex")
    dto = push_to_shell_item(
        {
            "push_id": 9,
            "item_id": 3,
            "subject": "math",
            "kp": "极限",
            "question": "# 求极限\n\n已知约束。\n\n$$a_n\\to 0$$",
            "answer": "0",
            "solution": {"steps": [{"text": "夹逼"}], "final_answer": "0"},
            "day": "2099-01-02",
            "answered": False,
        }
    )
    check(dto["id"] == "i3" and dto["pushId"] == 9, "shell item ids")
    check("answer" not in dto, "no answer leak")
    check(dto["kind"] == "math", "kind math")


def test_bootstrap_submit(tmp_db: str):
    os.environ["TEACHING_DB"] = tmp_db
    os.environ["PRACTICE_ALLOW_DEMO_SEED"] = "1"
    os.environ["PRACTICE_GRADE_MODE"] = "ref"
    os.environ["PRACTICE_WEB_HTTP"] = "1"
    os.environ["PRACTICE_WEB_HOST"] = "127.0.0.1"
    os.environ["PRACTICE_WEB_PORT"] = "18768"
    os.environ["PRACTICE_API_TOKEN"] = ""

    import importlib
    import config

    importlib.reload(config)
    import learner.db as dbmod

    importlib.reload(dbmod)
    from modules.bridge import practice_service as ps

    importlib.reload(ps)

    boot = ps.bootstrap("demo_learner")
    check(boot["ok"], "bootstrap ok")
    check(len(boot["slots"]) == 3, "3 slots")
    check(len(boot["items"]) >= 3, f"items>={len(boot['items'])}")
    today = [i for i in boot["items"] if not i.get("backlog")]
    check(len(today) >= 3, "today items")
    item = today[0]
    # math demo answer is 0
    math_item = next(i for i in today if i["kind"] == "math")
    sub = ps.submit(
        "demo_learner",
        answer="0",
        item=math_item["id"],
        push=math_item["pushId"],
        mode="ref",
    )
    check(sub["ok"] and sub["result"]["correct"] is True, "ref grade correct")
    boot2 = ps.bootstrap("demo_learner")
    check(math_item["id"] in boot2["answered"], "answered persisted")

    # HTTP layer
    from deliver import practice_web as pw

    importlib.reload(pw)
    httpd = pw.make_server("127.0.0.1", 18768)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", 18768, timeout=5)
        conn.request("GET", "/health")
        r = conn.getresponse()
        body = json.loads(r.read().decode())
        check(r.status == 200 and body.get("ok"), "http health")

        conn.request("GET", "/api/v1/agent/manifest")
        r = conn.getresponse()
        man = json.loads(r.read().decode())
        check(man.get("ok") and "tutor" in man.get("manifest", {}), "manifest")

        conn.request("GET", "/api/v1/practice/bootstrap?learner=demo_learner")
        r = conn.getresponse()
        b = json.loads(r.read().decode())
        check(b.get("ok") and b.get("slots"), "http bootstrap")

        conn.request(
            "POST",
            "/api/v1/tutor/chat",
            body=json.dumps({"learner": "demo_learner", "message": "hi"}),
            headers={"Content-Type": "application/json"},
        )
        r = conn.getresponse()
        tut = json.loads(r.read().decode())
        check(r.status == 501 and tut.get("error") == "tutor_agent_not_wired", "tutor stub")

        conn.request(
            "POST",
            "/api/v1/capability/events",
            body=json.dumps({
                "title": "考研专业课通过",
                "id": "grad_exam_major_pass",
                "domains": ["comm", "signals", "prob"],
                "p_hat": 0.32,
                "author": "test",
            }),
            headers={"Content-Type": "application/json"},
        )
        r = conn.getresponse()
        ev = json.loads(r.read().decode())
        check(r.status == 200 and ev.get("ok") and ev.get("upserted", {}).get("id") == "grad_exam_major_pass", "event upsert")

        conn.request("GET", "/api/v1/capability/events")
        r = conn.getresponse()
        el = json.loads(r.read().decode())
        check(el.get("ok") and el.get("count", 0) >= 1, "event list")

        conn.request("GET", "/practice")
        r = conn.getresponse()
        html = r.read().decode("utf-8", errors="replace")
        check(r.status == 200 and "API_BASE" in html and "/api/v1/practice/submit" in html, "shell")
    finally:
        httpd.shutdown()


def main():
    test_dto()
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        test_bootstrap_submit(db)
    print("ALL_OK")


if __name__ == "__main__":
    main()
