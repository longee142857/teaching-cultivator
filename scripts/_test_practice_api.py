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
        extract_options,
        extract_stem,
        parse_item_id,
        public_item_id,
        push_to_shell_item,
    )
    from modules.bridge.practice_service import _eta_map, _iter_mastery, practice_ocr

    check(public_item_id(12) == "i12", "public id")
    check(parse_item_id("i12") == 12, "parse i12")
    check(parse_item_id("12") == 12, "parse 12")
    katex = extract_katex(r"stem $$\lim x$$ tail")
    check("lim" in katex, "extract katex")
    surface = "已知曲面 $$z=x^{2}+y^{2}.$$ 求过点的切平面。"
    stem = extract_stem(surface)
    check("z=x^{2}+y^{2}" in stem and "切平面" in stem, "stem keeps display math")
    opts = extract_options("下列正确的是\nA. 可导\nB. 连续\nC. 可积\nD. 有界")
    check([o["letter"] for o in opts] == ["A", "B", "C", "D"], "mcq options")
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
    check("a_n" in (dto["stem"] or "") or "a_n" in (dto["katex"] or ""), "full problem math")
    dto2 = push_to_shell_item(
        {
            "item_id": 126,
            "subject": "math",
            "kp": "多元函数",
            "question": "曲面\n\n$$z=x^{2}+y^{2}.$$\n\n求过点的切平面。",
            "answered": False,
        }
    )
    check(dto2["title"] == "曲面", "title from first line")
    check(not (dto2["stem"] or "").startswith("曲面"), "stem drops duplicate title")
    check("z=x^{2}+y^{2}" in (dto2["stem"] or ""), "item 126-style equation stays")

    pairs = _iter_mastery(
        [{"kp": "极限", "p_mastery": 0.31}, {"kp": "卷积", "p_mastery": 0.72}]
    )
    check(pairs[0] == ("极限", 0.31) and pairs[1][0] == "卷积", "mastery list shape")
    pairs2 = _iter_mastery({"极限": {"p_mastery": 0.2}, "未分类": {"p": 0.1}})
    check(pairs2 == [("极限", 0.2)], "mastery dict shape skips 未分类")
    eta = _eta_map([{"domain": "calc", "eta": 0.4, "n_items": 2}])
    check(eta.get("calc") == 0.4, "eta list → map")
    ocr_empty = practice_ocr("")
    check(ocr_empty.get("error") == "empty_image", "ocr empty")
    ocr_unwired = practice_ocr(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    check(ocr_unwired.get("error") == "simpletex_not_configured", "ocr uses SimpleTex, unwired → 501 shape")
    from learner.paths import last_push_file_stale

    stale_path = os.path.join(tempfile.mkdtemp(), "last_push.json")
    with open(stale_path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": "2026-07-28T08:00:00+08:00", "question": "old mcq"}, f)
    check(last_push_file_stale(stale_path, "2026-08-12T08:00:00+08:00"), "old last_push skipped vs newer SQLite")
    check(not last_push_file_stale(stale_path, "2026-07-01T00:00:00+08:00"), "newer file not skipped")
    check(not last_push_file_stale(stale_path, ""), "no db ts → keep file fallback")


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
    from modules.store import get_store as _gs

    newest = _gs().get_newest_push()
    check(bool(newest and newest.get("question")), "newest push any-learner")
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
        check("path" not in el, "events JSON has no filesystem path")

        conn.request(
            "POST",
            "/api/v1/practice/ocr",
            body=json.dumps({"image": "", "filename": "a.jpg"}),
            headers={"Content-Type": "application/json"},
        )
        r = conn.getresponse()
        ocr = json.loads(r.read().decode())
        check(r.status == 400 and ocr.get("error") == "empty_image", "ocr empty image")

        man_ocr = (man.get("manifest") or {}).get("practice", {}).get("ocr") or {}
        check(man_ocr.get("path") == "/api/v1/practice/ocr", "manifest advertises ocr")

        conn.request("GET", "/practice")
        r = conn.getresponse()
        html = r.read().decode("utf-8", errors="replace")
        check(r.status == 200 and "API_BASE" in html and "/api/v1/practice/submit" in html, "shell")
        check("ocr-zone" not in html, "shell hides OCR chrome")
        check("/static/katex/katex.min.js" in html, "shell uses local KaTeX")
        font = ROOT / "web/static/katex/fonts/KaTeX_Main-Regular.woff2"
        check(font.is_file() and font.stat().st_size > 1000, "local KaTeX font present")
        check("canonicalItemId" in html, "numeric item alias in URL parse")
        check("讲师批改中" in html, "submit shows grading wait")
        check("从题库补练" in html, "empty slot CTA")

        nid = math_item.get("itemId")
        conn.request("GET", "/api/v1/practice/item?learner=demo_learner&item=" + str(nid))
        r = conn.getresponse()
        gotn = json.loads(r.read().decode())
        check(r.status == 200 and gotn.get("item", {}).get("id") == math_item["id"], "GET item numeric alias")

        conn.request("HEAD", "/practice")
        r = conn.getresponse()
        head_body = r.read()
        check(r.status == 200 and len(head_body) == 0, "HEAD /practice no body")
        check(int(r.getheader("Content-Length") or 0) > 0, "HEAD Content-Length")
    finally:
        httpd.shutdown()


def test_empty_day_and_capability(tmp_db: str):
    os.environ["TEACHING_DB"] = tmp_db
    os.environ["PRACTICE_ALLOW_DEMO_SEED"] = "0"
    os.environ["PRACTICE_GRADE_MODE"] = "ref"

    import importlib
    import config

    importlib.reload(config)
    import learner.db as dbmod

    importlib.reload(dbmod)
    from modules.bridge import practice_service as ps

    importlib.reload(ps)
    from modules.store import get_store

    store = get_store()
    store.set_mastery(
        "cap_learner",
        "极限",
        {"p_mastery": 0.28, "opportunity_count": 4, "is_mastered": False},
    )
    store.set_mastery(
        "cap_learner",
        "卷积",
        {"p_mastery": 0.81, "opportunity_count": 6, "is_mastered": True},
    )
    store.insert_bank_item(
        subject="math",
        question="曲面\n\n$$z=x^{2}+y^{2}.$$\n\n求过点的切平面。",
        answer="切平面",
        kp="极限",
        status="ready",
    )
    store.insert_bank_item(
        subject="comm",
        question="系统输出\n\n$$y(t)=x*h$$\n\n写出卷积定义。",
        answer="卷积",
        kp="卷积",
        status="ready",
    )
    store.insert_bank_item(
        subject="review",
        question="复习\n\n$$f'(x)=2x$$\n\n求 f(1)。",
        answer="2",
        kp="导数",
        status="ready",
    )

    cap = ps._params_summary("cap_learner")
    check("error" not in cap, "capability no list.items error")
    check(any(w["kp"] == "极限" for w in cap.get("masteryWeak") or []), "masteryWeak from list")
    check(isinstance(cap.get("eta"), dict), "eta is dict")

    boot = ps.bootstrap("cap_learner")
    check(boot["ok"], "empty-day bootstrap ok")
    check((boot.get("capability") or {}).get("error") in (None, ""), "bootstrap capability clean")
    check(any(s.get("itemId") for s in boot.get("slots") or []), "empty-day slots filled from bank")
    today = [i for i in boot.get("items") or [] if not i.get("backlog")]
    check(len(today) >= 1, "empty-day has reachable bank item")
    check(any(i.get("fromBank") for i in today), "items marked fromBank")
    math_it = next((i for i in today if i.get("kind") == "math"), today[0])
    check(
        "z=x^{2}+y^{2}" in (math_it.get("stem") or "")
        or "z=x^{2}+y^{2}" in (math_it.get("katex") or ""),
        "bank item keeps surface equation",
    )
    got = ps.get_item("cap_learner", item=math_it["id"])
    check(got.get("ok") and got.get("item", {}).get("itemId"), "GET item without push")
    got_num = ps.get_item("cap_learner", item=str(math_it["itemId"]))
    check(got_num.get("ok") and got_num.get("item", {}).get("id") == math_it["id"], "GET item accepts bare 126")
    picked = ps.get_item("cap_learner", kind="math")
    check(picked.get("ok") and picked.get("item", {}).get("kind") == "math", "GET item kind=math picks ready")

    exam_html = (ROOT / "web/static/exam.html").read_text(encoding="utf-8")
    check('maxlength="24"' in exam_html, "exam uid maxlength allows 20-digit")
    check("[0-9]{1,24}" in exam_html, "exam uid regex allows 20-digit")


def main():
    test_dto()
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        test_bootstrap_submit(db)
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t2.db")
        test_empty_day_and_capability(db)
    print("ALL_OK")


if __name__ == "__main__":
    main()
