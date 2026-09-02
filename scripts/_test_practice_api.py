# -*- coding: utf-8 -*-
"""Practice desk API + DTO smoke (no LLM)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_kl = ROOT / "knowledge-lib"
if _kl.is_dir():
    sys.path.insert(0, str(_kl))
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
    store = _gs()
    atts = [
        a
        for a in store.get_attempts("demo_learner")
        if a.get("item_id") == math_item.get("itemId")
    ]
    check(atts and atts[-1].get("item_id") == math_item.get("itemId"), "demo submit writes item_id")
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
        check("ocr-zone" in html and "选择手写图片" in html, "shell exposes OCR chrome")
        check("公式加强" in html and "整页识别" in html, "shell OCR mode toggle")
        check("/static/katex/katex.min.js" in html, "shell uses local KaTeX")
        font = ROOT / "web/static/katex/fonts/KaTeX_Main-Regular.woff2"
        check(font.is_file() and font.stat().st_size > 1000, "local KaTeX font present")
        check("canonicalItemId" in html, "numeric item alias in URL parse")
        check("讲师批改中" in html, "submit shows grading wait")
        check("pollGradeUntilDone" in html, "shell polls until grade lands")
        check("请勿重复提交" in html, "poll timeout does not say 提交失败")
        check('status === "grading"' in html, "in-flight grading ≠ DB pending")
        check("从题库补练" in html, "empty slot CTA")
        check("sameScreen" in html and "keepY" in html, "same-view render keeps scroll")
        check("window.scrollTo(0, 0)" in html, "view-change still may scroll to top")
        check("answer-preview" in html and "paintDraftPreview" in html, "OCR/source live KaTeX preview")
        check("throwOnError: false" in html, "preview KaTeX fails soft")
        check("提交仍用上方原文" in html, "submit uses edited source not HTML")

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


def _llm_ok(_system, _user, task_type="grade", *_a, **_k):
    if task_type == "verify_grade":
        return json.dumps(
            {"agrees": True, "confidence": 0.9, "reasoning": "ok"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"verdict": "correct", "confidence": 0.95, "explanation": "ok"},
        ensure_ascii=False,
    )


def _llm_pending(_system, _user, task_type="grade", *_a, **_k):
    if task_type == "verify_grade":
        return json.dumps(
            {"agrees": True, "confidence": 0.2, "reasoning": "unsure"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"verdict": "correct", "confidence": 0.3, "explanation": "low"},
        ensure_ascii=False,
    )


def _await_practice_grade(ps, learner: str, item, push=None, timeout: float = 4.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        got = ps.get_item(learner, item=item, push=push)
        last = got
        r = (got or {}).get("result") or {}
        if (
            got.get("ok")
            and r
            and r.get("status") != "grading"
            and not got.get("grading")
        ):
            return got
        time.sleep(0.05)
    return last


def _submit_and_wait(ps, learner: str, **kwargs):
    """Submit; if LLM open/proof returns pending, poll GET item until done."""
    sub = ps.submit(learner, **kwargs)
    if sub.get("pending") or sub.get("grading") or (
        (sub.get("result") or {}).get("status") == "grading"
    ):
        got = _await_practice_grade(
            ps, learner, kwargs.get("item"), kwargs.get("push")
        )
        if got and got.get("result"):
            merged = dict(sub)
            merged["ok"] = bool(got.get("ok"))
            merged["result"] = got["result"]
            merged["item"] = got.get("item") or sub.get("item")
            merged.pop("pending", None)
            merged.pop("grading", None)
            return merged
    return sub


def _assert_last_item_id(store, learner: str, item_id: int, msg: str) -> None:
    atts = store.get_attempts(learner)
    check(atts, msg + " (has attempt)")
    last = atts[-1]
    check(last.get("item_id") is not None, msg + " (item_id not null)")
    check(int(last["item_id"]) == int(item_id), f"{msg} (item_id={last.get('item_id')} want={item_id})")


def test_submit_persists_item_id(tmp_db: str):
    """Every practice submit path writes a non-null attempts.item_id."""
    os.environ["TEACHING_DB"] = tmp_db
    os.environ["PRACTICE_ALLOW_DEMO_SEED"] = "0"
    os.environ["PRACTICE_GRADE_MODE"] = "ref"

    import importlib
    from unittest.mock import patch

    import config

    importlib.reload(config)
    import learner.db as dbmod

    importlib.reload(dbmod)
    from modules.bridge import practice_service as ps

    importlib.reload(ps)
    from learner.context import bind_learner
    from modules.store import get_store

    store = get_store()
    q_bank = "空日补槽\n\n$$x+1=2$$\n\n求 x。"
    iid = store.insert_bank_item(
        subject="math",
        question=q_bank,
        answer="1",
        kp="极限",
        status="ready",
        solution={"steps": [{"text": "移项"}], "final_answer": "1"},
    )
    q_push = "有推送题\n\n$$2+2=$$\n\n求值。"
    iid_push = store.insert_bank_item(
        subject="math",
        question=q_push,
        answer="4",
        kp="极限",
        status="ready",
        solution={"final_answer": "4"},
    )
    pid = store.record_push_for_item(
        item_id=iid_push,
        learner_id="id_learner",
        slot="math",
        reason="test:push",
    )

    # 1) empty-day / fromBank: grade_answer applied (no push)
    from grade import grade_answer

    with bind_learner("id_learner", binding="personal"):
        with patch("grade.call_llm", side_effect=_llm_ok), patch(
            "learner.kp_registry.normalize_kp_for_grade", return_value="极限"
        ), patch("learner.weights_ops.bump_kp_weight"), patch(
            "learner.weights_ops.decay_kp_weight"
        ):
            r = grade_answer(q_bank, "1", kp_name="极限", subject="math")
    check(r.status == "applied", "grade applied no-push")
    _assert_last_item_id(store, "id_learner", iid, "grade_answer applied no-push")

    # 2) empty-day: grade_answer pending (no push)
    q_pend = "待审题\n\n$$3+3=$$\n\n求值。"
    iid_pend = store.insert_bank_item(
        subject="math", question=q_pend, answer="6", kp="极限", status="ready"
    )
    with bind_learner("id_learner", binding="personal"):
        with patch("grade.call_llm", side_effect=_llm_pending), patch(
            "learner.kp_registry.normalize_kp_for_grade", return_value="极限"
        ):
            r = grade_answer(q_pend, "6", kp_name="极限", subject="math")
    check(r.status == "pending", f"grade pending no-push got {r.status}")
    _assert_last_item_id(store, "id_learner", iid_pend, "grade_answer pending no-push")

    # 3) submit ref, no push_id (bank-filled slot)
    boot = ps.bootstrap("id_learner")
    check(boot.get("ok"), "bootstrap for id tests")
    bank_it = next(
        (
            i
            for i in boot.get("items") or []
            if i.get("itemId") == iid and not i.get("pushId")
        ),
        None,
    )
    if bank_it is None:
        # already answered via grade_answer above — pick a fresh bank item
        q_ref = "再补一题\n\n$$5-1=$$\n\n求值。"
        iid_ref = store.insert_bank_item(
            subject="comm",
            question=q_ref,
            answer="4",
            kp="卷积",
            status="ready",
            solution={"final_answer": "4"},
        )
        sub = ps.submit("id_learner", answer="4", item=f"i{iid_ref}", push=None, mode="ref")
        check(sub.get("ok"), "ref submit no-push ok")
        _assert_last_item_id(store, "id_learner", iid_ref, "submit ref no-push")
    else:
        sub = ps.submit(
            "id_learner",
            answer="1",
            item=bank_it["id"],
            push=bank_it.get("pushId"),
            mode="ref",
        )
        check(sub.get("ok"), "ref submit no-push ok")
        _assert_last_item_id(store, "id_learner", iid, "submit ref no-push")

    # 4) submit llm (mocked), no push_id
    q_llm = "LLM 空日题\n\n$$7-3=$$\n\n求值。"
    iid_llm = store.insert_bank_item(
        subject="review",
        question=q_llm,
        answer="4",
        kp="导数",
        status="ready",
        solution={"final_answer": "4"},
    )
    with patch("grade.call_llm", side_effect=_llm_ok), patch(
        "learner.kp_registry.normalize_kp_for_grade", return_value="导数"
    ), patch("learner.weights_ops.bump_kp_weight"), patch(
        "learner.weights_ops.decay_kp_weight"
    ):
        sub = _submit_and_wait(
            ps, "id_learner", answer="4", item=f"i{iid_llm}", push=None, mode="llm"
        )
    check(sub.get("ok") and sub.get("result", {}).get("gradeMode") == "llm", "llm submit no-push")
    hits = [a for a in store.get_attempts("id_learner") if a.get("item_id") == iid_llm]
    check(len(hits) == 1 and hits[0].get("item_id") == iid_llm, "submit llm no-push one row")

    # 5) submit llm raises → ref_fallback, no push_id
    q_fb = "回退题\n\n$$9-5=$$\n\n求值。"
    iid_fb = store.insert_bank_item(
        subject="math",
        question=q_fb,
        answer="4",
        kp="极限",
        status="ready",
        solution={"final_answer": "4"},
    )
    with patch("grade.grade_answer", side_effect=RuntimeError("llm down")):
        sub = _submit_and_wait(
            ps, "id_learner", answer="4", item=f"i{iid_fb}", push=None, mode="llm"
        )
    check(sub.get("ok") and sub.get("result", {}).get("gradeMode") == "ref_fallback", "ref_fallback no-push")
    _assert_last_item_id(store, "id_learner", iid_fb, "submit ref_fallback no-push")

    # 6) submit ref with push
    sub = ps.submit(
        "id_learner", answer="4", item=f"i{iid_push}", push=pid, mode="ref"
    )
    check(sub.get("ok"), "ref submit with push")
    hits = [
        a
        for a in store.get_attempts("id_learner")
        if a.get("item_id") == iid_push and a.get("push_id") == pid
    ]
    check(hits and hits[-1].get("item_id") == iid_push, "submit ref with push item_id")

    # 7) submit llm with push
    q_llm_p = "有推送 LLM\n\n$$8/2=$$\n\n求值。"
    iid_llm_p = store.insert_bank_item(
        subject="math",
        question=q_llm_p,
        answer="4",
        kp="极限",
        status="ready",
        solution={"final_answer": "4"},
    )
    pid2 = store.record_push_for_item(
        item_id=iid_llm_p, learner_id="id_learner", slot="math", reason="test:llm-push"
    )
    with patch("grade.call_llm", side_effect=_llm_ok), patch(
        "learner.kp_registry.normalize_kp_for_grade", return_value="极限"
    ), patch("learner.weights_ops.bump_kp_weight"), patch(
        "learner.weights_ops.decay_kp_weight"
    ):
        sub = _submit_and_wait(
            ps,
            "id_learner",
            answer="4",
            item=f"i{iid_llm_p}",
            push=pid2,
            mode="llm",
        )
    check(sub.get("ok") and sub.get("result", {}).get("gradeMode") == "llm", "llm submit with push")
    hits = [
        a
        for a in store.get_attempts("id_learner")
        if a.get("item_id") == iid_llm_p
    ]
    check(len(hits) == 1 and hits[0].get("item_id") == iid_llm_p, "submit llm with push item_id")
    check(hits[0].get("push_id") == pid2, "submit llm with push keeps push_id")


def test_async_grade_and_idempotent(tmp_db: str):
    """Proof LLM submit returns pending; second click does not double-write."""
    os.environ["TEACHING_DB"] = tmp_db
    os.environ["PRACTICE_ALLOW_DEMO_SEED"] = "0"
    os.environ["PRACTICE_GRADE_MODE"] = "llm"

    import importlib
    from unittest.mock import patch

    import config

    importlib.reload(config)
    import learner.db as dbmod

    importlib.reload(dbmod)
    from modules.bridge import practice_service as ps

    importlib.reload(ps)
    from grade import GradeResult
    from modules.store import get_store

    store = get_store()

    # ref path: two submits → one attempt, second is already
    q_ref = "幂级数\n\n$$\\sum x^n$$\n\n求半径。"
    iid_ref = store.insert_bank_item(
        subject="math",
        question=q_ref,
        answer="1",
        kp="极限",
        status="ready",
        solution={"final_answer": "1"},
    )
    sub1 = ps.submit("idem_learner", answer="1", item=f"i{iid_ref}", push=None, mode="ref")
    check(sub1.get("ok") and not sub1.get("pending"), "ref submit sync")
    sub2 = ps.submit("idem_learner", answer="1", item=f"i{iid_ref}", push=None, mode="ref")
    check(sub2.get("already"), "second ref submit already")
    hits = [a for a in store.get_attempts("idem_learner") if a.get("item_id") == iid_ref]
    check(len(hits) == 1, "ref resubmit does not add a second attempt")
    got = ps.get_item("idem_learner", item=f"i{iid_ref}")
    check(got.get("result") and got["item"].get("answered"), "GET item hydrates by item_id")

    q_proof = "求证：循环码的生成多项式整除 x^n-1。"
    iid_p = store.insert_bank_item(
        subject="comm",
        question=q_proof,
        answer="g(x)|x^n-1",
        kp="循环码",
        status="ready",
    )
    gate = threading.Event()
    started = threading.Event()
    calls = {"n": 0}

    def slow_grade(*_a, **_k):
        calls["n"] += 1
        started.set()
        if not gate.wait(timeout=5):
            raise RuntimeError("grade gate timeout")
        return GradeResult(
            is_correct=False,
            feedback="生成多项式整除 x^n-1 的证明要点。",
            kp_name="循环码",
            subject="comm",
            credit=0.5,
            item_type="proof_outline",
            status="applied",
            confidence=0.9,
            p_mastery_before=0.2,
            p_mastery_after=0.25,
        )

    with patch("grade.grade_answer", side_effect=slow_grade):
        t0 = time.monotonic()
        sub_p = ps.submit(
            "idem_learner",
            answer="设 g(x) 为生成多项式，则…",
            item=f"i{iid_p}",
            push=None,
            mode="llm",
        )
        elapsed = time.monotonic() - t0
        check(sub_p.get("ok") and sub_p.get("pending"), "proof llm submit returns pending")
        check((sub_p.get("result") or {}).get("status") == "grading", "pending status=grading")
        check(elapsed < 1.0, f"pending returns quickly ({elapsed:.3f}s)")
        check(started.wait(2), "worker started before gate release")
        mid = [a for a in store.get_attempts("idem_learner") if a.get("item_id") == iid_p]
        check(len(mid) == 0, "no attempt until lecturer grade finishes")
        sub_again = ps.submit(
            "idem_learner",
            answer="另一份解答",
            item=f"i{iid_p}",
            push=None,
            mode="llm",
        )
        check(sub_again.get("pending") or sub_again.get("grading"), "inflight second click pending")
        check(calls["n"] == 1, "second click does not start another grade")
        gate.set()
        landed = _await_practice_grade(ps, "idem_learner", f"i{iid_p}", timeout=4.0)
    check(landed and (landed.get("result") or {}).get("credit") == 0.5, "poll sees 半对")
    check((landed.get("result") or {}).get("partial"), "hydrated result marks partial")
    hits_p = [a for a in store.get_attempts("idem_learner") if a.get("item_id") == iid_p]
    check(len(hits_p) == 1, "async proof writes one attempt")
    sub3 = ps.submit(
        "idem_learner",
        answer="请再批一次",
        item=f"i{iid_p}",
        push=None,
        mode="llm",
    )
    check(sub3.get("already"), "after grade, resubmit is already")
    hits_p2 = [a for a in store.get_attempts("idem_learner") if a.get("item_id") == iid_p]
    check(len(hits_p2) == 1, "already path does not insert another attempt")

    q_mcq = "下列正确的是\nA. 可导\nB. 连续\nC. 可积\nD. 有界"
    iid_m = store.insert_bank_item(
        subject="math", question=q_mcq, answer="A", kp="极限", status="ready"
    )

    def fast_grade(*_a, **_k):
        return GradeResult(
            is_correct=True,
            feedback="选 A。",
            kp_name="极限",
            subject="math",
            item_type="mcq",
            status="applied",
            confidence=0.95,
        )

    with patch("grade.grade_answer", side_effect=fast_grade):
        sub_m = ps.submit(
            "idem_learner", answer="A", item=f"i{iid_m}", push=None, mode="llm"
        )
    check(sub_m.get("ok") and not sub_m.get("pending"), "mcq llm stays synchronous")
    check((sub_m.get("result") or {}).get("gradeMode") == "llm", "mcq llm gradeMode")


def main():
    test_dto()
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        test_bootstrap_submit(db)
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t2.db")
        test_empty_day_and_capability(db)
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t3.db")
        test_submit_persists_item_id(db)
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t4.db")
        test_async_grade_and_idempotent(db)
    print("ALL_OK")


if __name__ == "__main__":
    main()
