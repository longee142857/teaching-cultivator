# -*- coding: utf-8 -*-
"""预出题库 / pick / CDP 对齐单测（无真网）。"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_KL = os.path.join(ROOT, "knowledge-lib")
if _KL not in sys.path:
    sys.path.insert(0, _KL)


def _ensure_cultivate_deps() -> None:
    """本机/CI 可能缺 knowledge-system；为 import cultivate 提供最小 stub。"""
    from types import ModuleType, SimpleNamespace

    iv = ModuleType("intervention")

    class InterventionDecision(SimpleNamespace):
        pass

    def decide_intervention(**kwargs):
        return InterventionDecision(**kwargs)

    iv.InterventionDecision = InterventionDecision
    iv.decide_intervention = decide_intervention
    sys.modules["intervention"] = iv

    if "heartbeat_summary" not in sys.modules:
        hb = ModuleType("heartbeat_summary")
        hb.extract = lambda *a, **k: {}
        sys.modules["heartbeat_summary"] = hb


_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def _mark_pass(store, item_id: int) -> None:
    store.apply_judge_verdict(int(item_id), verdict="pass", reasons=["test"], confidence=1.0)


def test_schema_and_pick() -> None:
    from learner.db import Store
    from learner.item_bank import validate_bank_payload, align_cdp_results, pick_for_push
    from cultivate_bank import pregenerate_one

    with tempfile.TemporaryDirectory() as td:
        dbp = os.path.join(td, "t.db")
        store = Store(dbp)
        # migrate columns exist
        cols = {r[1] for r in store._query("PRAGMA table_info(items)")}
        for c in ("status", "bank_subject", "techniques", "solution", "cdps"):
            check(c in cols, f"items.{c} column")

        cdps = [
            {"id": "cdp1", "prompt": "p1", "expected": "e1", "technique": "t_a", "depends_on": []},
            {"id": "cdp2", "prompt": "p2", "expected": "e2", "technique": "t_a", "depends_on": ["cdp1"]},
        ]
        sol = {"steps": [{"id": "s1", "text": "step"}], "final_answer": "42", "techniques_used": ["t_a"]}
        err = validate_bank_payload(
            question="Q?", techniques=["t_a"], solution=sol, cdps=cdps
        )
        check(err == "", "validate ok")

        iid = store.insert_bank_item(
            subject="math",
            question="极限题干甲",
            answer="42",
            kp="极限",
            techniques=["t_a"],
            solution=sol,
            cdps=cdps,
            status="ready",
        )
        check(iid > 0, "insert bank item")
        check(store.count_ready("math") == 0, "pending not counted as pass")
        _mark_pass(store, iid)
        check(store.count_ready("math") == 1, "ready count 1")
        check(store.count_ready("math", kp="极限", technique="t_a") == 1, "ready by tech")

        # second item different kp
        iid2 = store.insert_bank_item(
            subject="math",
            question="级数题干乙",
            answer="1",
            kp="幂级数与函数展开",
            techniques=["series"],
            solution=sol,
            cdps=cdps,
            status="ready",
        )
        _mark_pass(store, iid2)

        hit = store.pick_ready_item(subject="math", kp="极限", technique="t_a")
        check(hit and hit["kp"] == "极限", "pick KP+tech")
        hit2 = store.pick_ready_item(subject="math", kp="不存在的KP")
        check(hit2 is None, "unknown KP does not widen to any ready")

        # push for item
        pid = store.record_push_for_item(item_id=iid, learner_id="u1", reason="极限")
        check(pid > 0, "record_push_for_item")
        push = store.get_push(pid)
        check(push and push.get("cdps"), "push row exposes cdps")

        aligned, ok = align_cdp_results(
            cdps,
            [{"id": "cdp1", "ok": True, "technique": "t_a", "note": ""},
             {"id": "cdp2", "ok": False, "technique": "t_a", "note": "miss"}],
        )
        check(ok and len(aligned) == 2 and aligned[1]["ok"] is False, "align cdp ok")
        check(aligned[1].get("attributable") is True, "real fail attributable")
        aligned2, ok2 = align_cdp_results(cdps, [{"id": "cdp1", "ok": True}])
        check(ok2 is False and len(aligned2) == 2, "align missing cdp2")
        check(aligned2[1].get("attributable") is False, "missing not attributable")
        from learner.item_bank import learner_cdp_fail_summary, is_learner_cdp_fail
        check(not is_learner_cdp_fail(aligned2[1]), "missing_from_grade filtered")
        sum_noise = learner_cdp_fail_summary(aligned2)
        check(sum_noise["technique_failures"] == [] and sum_noise["cdp_fail_ids"] == [],
              "align noise not in fail summary")
        sum_real = learner_cdp_fail_summary(aligned)
        check(sum_real["cdp_fail_ids"] == ["cdp2"], "real fail kept in summary")
        aligned3, ok3 = align_cdp_results(cdps, [{"id": "cdp1"}, {"id": "cdp2", "ok": True}])
        check(ok3 is False and aligned3[0].get("ok") is None, "missing ok field")
        check(not is_learner_cdp_fail(aligned3[0]), "missing ok not learner fail")

        # recent_ability_signals 过滤对齐噪声
        store.add_attempt_entry({
            "user_id": "u_noise",
            "knowledge_point": "极限",
            "correct": False,
            "answered_at": "2026-08-12T00:00:00+00:00",
            "cdp_results": aligned2,
            "status": "pending",
        })
        sig_n = store.recent_ability_signals("u_noise")
        check(sig_n.get("technique_fail_top") == [], "signals ignore align noise")
        check(sig_n.get("cdp_fail_recent") == [], "cdp_fail ignore align noise")

        # max_items gate
        r = pregenerate_one("math", max_items=2)
        check(r.get("error") == "max_items_must_be_1", "pregen max_items=1 enforced")

        # ability snapshot
        store.add_ability_snapshot("u1", {"technique_failures": ["t_a"]})
        check(store.count_rows("ability_snapshots") >= 1, "ability_snapshots write")
        sig = store.recent_ability_signals("u1")
        check(isinstance(sig, dict) and "technique_fail_top" in sig, "recent signals shape")

        # judge: poor 权重低于 pass → 同 KP 优先抽非 poor
        cols2 = {r[1] for r in store._query("PRAGMA table_info(items)")}
        for c in ("quality_tier", "quality_score", "judge_count", "judge_meta"):
            check(c in cols2, f"items.{c} column")

        good = store.insert_bank_item(
            subject="math",
            question="优质极限题",
            answer="0",
            kp="极限",
            techniques=["t_a"],
            solution=sol,
            cdps=cdps,
        )
        bad = store.insert_bank_item(
            subject="math",
            question="劣质极限题",
            answer="0",
            kp="极限",
            techniques=["t_a"],
            solution=sol,
            cdps=cdps,
        )
        store.apply_judge_verdict(good, verdict="pass", reasons=[], confidence=0.9)
        store.apply_judge_verdict(bad, verdict="fail", reasons=["hallucination"], confidence=0.9)
        # 同档其它题降为 poor，只留 good 为高分
        for row in store._query(
            "SELECT id FROM items WHERE status='ready' AND kp=? AND id!=?",
            ("极限", good),
        ):
            store.apply_judge_verdict(int(row[0]), verdict="fail", reasons=["setup"], confidence=1.0)
        g = store.get_item(good)
        b = store.get_item(bad)
        check(g and g["quality_tier"] == "pass" and float(g["quality_score"]) >= 0.9, "pass tier")
        check(b and b["quality_tier"] == "poor" and float(b["quality_score"]) <= 0.2, "poor tier")
        picked = store.pick_ready_item(subject="math", kp="极限", technique="t_a")
        check(picked and int(picked["id"]) == good, "pick prefers pass over poor")

        from cultivate_judge import run_judge_slot, JUDGE_SLOTS
        check(len(JUDGE_SLOTS) == 2, "two judge slots")
        # machine-only: 污染词 → fail without LLM
        junk = store.insert_bank_item(
            subject="math",
            question="我们调整一下重新出题",
            answer="1",
            kp="极限",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
        )
        with patch("cultivate_judge.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store):
            jr = run_judge_slot(max_items=5, use_llm=False)
        check(jr.get("ok") is True, "judge slot ok")
        junk_after = store.get_item(junk)
        check(
            junk_after and junk_after.get("quality_tier") == "poor",
            "contaminated marked poor",
        )


def test_cultivate_uses_bank_no_author() -> None:
    """槽位路径 mock：有 ready 时不调用 generate。"""
    from types import SimpleNamespace
    from learner.db import Store
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        dbp = os.path.join(td, "t.db")
        store = Store(dbp)
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
        cdps = [
            {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
            {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
        ]
        store.insert_bank_item(
            subject="math",
            question="银行题干",
            answer="1",
            kp="极限",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
        )
        # pending 不可抽；过审后走 bank
        pending_hit = store.pick_ready_item(subject="math", kp="极限")
        check(pending_hit is None, "pending not pickable")
        rows = store._query("SELECT id FROM items WHERE question=?", ("银行题干",))
        _mark_pass(store, rows[0][0])

        called = {"generate": 0}

        def fake_generate(*a, **k):
            called["generate"] += 1
            return ""

        decision = SimpleNamespace(
            type="push", difficulty="basic", reason="极限", ability_goal="compute"
        )

        with patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.deliver", return_value=True), \
             patch("cultivate._save_last_push"), \
             patch("cultivate._bkt_available", True), \
             patch("cultivate.DATA_DIR", td), \
             patch("cultivate.DAILY_RECORD_DIR", td), \
             patch("learner.item_bank.pick_technique_for_kp", return_value="t"):
            from cultivate import _cultivate_inner
            with bind_learner("staff1", binding="schedule"):
                _cultivate_inner("math")
        check(called["generate"] == 0, "cultivate bank path zero author")
        check(store.count_rows("pushes") == 1, "cultivate created push")
        qdir = os.path.join(td, "sync-queue")
        qfiles = [f for f in os.listdir(qdir) if f.endswith(".md")] if os.path.isdir(qdir) else []
        check(len(qfiles) == 1, "bank path wrote sync-queue")
        if qfiles:
            body = open(os.path.join(qdir, qfiles[0]), encoding="utf-8").read()
            check("银行题干" in body, "sync-queue contains bank question")


def test_author_spec_inserts_ready() -> None:
    """驱动 _author_spec 走完整入库路径（曾因提取后丢 store 而 NameError）。"""
    from learner.db import Store
    from types import SimpleNamespace
    from cultivate_bank import _author_spec

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        decision = SimpleNamespace(
            type="push", difficulty="basic",
            reason="函数极限与连续 [l3=math.calc.limit.def] [ability=recognize]",
            ability_goal="recognize",
        )
        structured = {
            "techniques": ["t_a"],
            "solution": {"steps": [{"id": "s1", "text": "步骤"}],
                         "final_answer": "答案", "techniques_used": ["t_a"]},
            "cdps": [{"id": "c1", "prompt": "p", "expected": "e", "technique": "t_a", "depends_on": []},
                     {"id": "c2", "prompt": "p2", "expected": "e2", "technique": "t_a", "depends_on": ["c1"]}],
        }
        with patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("cultivate_bank.get_store", return_value=store), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", return_value="题干内容X"), \
             patch("cultivate.get_last_answer", return_value="答案X"), \
             patch("cultivate.get_last_ref_source", return_value="2024年数学一"), \
             patch("cultivate.get_last_item_form", return_value="mcq"), \
             patch("cultivate._bkt_available", True), \
             patch("learner.kp_registry.pick_l3", return_value="math.calc.limit.def"), \
             patch("learner.kp_registry.list_l3_for_l2", return_value=[{"id": "x"}]), \
             patch("cultivate_bank.structure_item_via_llm", return_value=structured):
            spec = {"kp": "函数极限与连续", "technique": "t_a", "subject": "math"}
            r = _author_spec("math", spec)
        check(r.get("ok") is True, "author_spec ok")
        check(store.count_ready("math") == 0, "inserted pending not counted")
        iid = r.get("item_id")
        check(iid and store.get_item(iid), "item inserted")
        it = store.get_item(iid)
        check((it.get("ref_source") or "") == "2024年数学一", "math ref kept")
        check((it.get("meta") or {}).get("content_subject") == "math", "content_subject math")


def test_author_spec_keeps_explain_type() -> None:
    """预生成不得把 explain 改成 push。"""
    from learner.db import Store
    from types import SimpleNamespace
    from cultivate_bank import _author_spec

    captured: dict = {}

    def fake_generate(_subj, decision, **_k):
        captured["type"] = decision.type
        captured["ability"] = getattr(decision, "ability_goal", "")
        return "讲解稿加巩固题"

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        decision = SimpleNamespace(
            type="explain", difficulty="basic",
            reason="函数极限与连续 [l3=math.calc.limit.def] [ability=recognize]",
            ability_goal="recognize",
        )
        structured = {
            "techniques": ["t_a"],
            "solution": {"steps": [{"id": "s1", "text": "步骤"}],
                         "final_answer": "答案", "techniques_used": ["t_a"]},
            "cdps": [{"id": "c1", "prompt": "p", "expected": "e", "technique": "t_a", "depends_on": []},
                     {"id": "c2", "prompt": "p2", "expected": "e2", "technique": "t_a", "depends_on": ["c1"]}],
        }
        with patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("cultivate_bank.get_store", return_value=store), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.get_last_answer", return_value="答案X"), \
             patch("cultivate.get_last_ref_source", return_value="2024年数学一"), \
             patch("cultivate.get_last_item_form", return_value="mcq"), \
             patch("cultivate._bkt_available", True), \
             patch("learner.kp_registry.pick_l3", return_value="math.calc.limit.def"), \
             patch("learner.kp_registry.list_l3_for_l2", return_value=[{"id": "x"}]), \
             patch("cultivate_bank.structure_item_via_llm", return_value=structured):
            spec = {"kp": "函数极限与连续", "technique": "t_a", "subject": "math"}
            r = _author_spec("math", spec)
        check(r.get("ok") is True, "explain author ok")
        check(captured.get("type") == "explain", f"kept explain {captured}")
        check(captured.get("ability") == "recognize", f"explain ability {captured}")


def test_pregen_fallback_next_gap() -> None:
    """首个缺口出题失败后，预生成回退到次优缺口。"""
    from learner.db import Store
    from cultivate_bank import _pregenerate_one_inner

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        calls = {"n": 0}

        def fake_select(subject, skip_kps=None):
            if "A" in (skip_kps or set()):
                return {"kp": "B", "technique": "", "subject": subject}
            return {"kp": "A", "technique": "", "subject": subject}

        def fake_author(subject, spec):
            calls["n"] += 1
            if spec["kp"] == "A":
                return {"ok": False, "error": "generate_failed", "kp": "A", "subject": subject}
            return {"ok": True, "skipped": False, "item_id": 1, "kp": "B", "subject": subject}

        with patch("cultivate_bank.get_store", return_value=store), \
             patch("cultivate_bank.select_gap_spec", side_effect=fake_select), \
             patch("cultivate_bank._author_spec", side_effect=fake_author):
            r = _pregenerate_one_inner("math")
        check(r.get("ok") is True, "fallback picks next gap after fail")
        check(calls["n"] == 2, "author tried A(fail) then B(ok)")


def test_offpeak_slots_and_ref_gate() -> None:
    from cultivate_bank import PREGEN_SLOTS, _sanitize_ref_source
    from cultivate_judge import JUDGE_SLOTS
    from learner.kp_registry import parse_content_subject_from_reason
    from orchestrate import _strip_bank_transition

    hours = [t for t, _ in PREGEN_SLOTS]
    check(hours == ["00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00"],
          f"pregen off-peak slots (got {hours})")
    check(JUDGE_SLOTS == ["05:30", "08:30"], f"judge slots {JUDGE_SLOTS}")
    check(_sanitize_ref_source("math", "2024年通信原理") == "", "math rejects comm source")
    check(_sanitize_ref_source("comm", "2024年数学一") == "", "comm rejects math source")
    check(_sanitize_ref_source("math", "2024年数学一") == "2024年数学一", "math keeps 数学一")
    check(_sanitize_ref_source("comm", "2023年通信原理") == "2023年通信原理", "comm keeps 通信原理")
    check(parse_content_subject_from_reason("极限: x [content_subject=comm]") == "comm",
          "parse content_subject")
    stripped = _strip_bank_transition("上一题你刚做完极限。\n\n求 lim x→0 sinx/x")
    check(not stripped.startswith("上一题") and "sinx" in stripped, "strip fake transition")
    check("11:00" not in hours, "no 11:00 peak pregen")
    check("review" not in [s for _, s in PREGEN_SLOTS], "no review pregen slots")


def test_review_pregen_and_fill_skip() -> None:
    from cultivate_bank import _pregenerate_one_inner, run_pregen_slot

    with patch("cultivate_bank.select_gap_spec") as gap, \
         patch("cultivate_bank._author_spec") as auth:
        r = _pregenerate_one_inner("review")
    check(r.get("skipped") is True, f"review pregen skipped {r}")
    check(r.get("reason") == "review_live_only", r)
    check(not gap.called, "review must not gap-fill")
    check(not auth.called, "review must not author in pregen")

    class _S:
        def count_ready(self, s):
            return 0 if s == "review" else 99

    with patch("cultivate_bank.get_store", return_value=_S()), \
         patch("cultivate_bank.bank_quota", return_value=6), \
         patch("cultivate_bank.pregenerate_one") as pre:
        fill = run_pregen_slot("fill")
    check(fill.get("reason") == "all_full", f"fill should ignore review gap {fill}")
    check(not pre.called, "fill must not pregenerate review")


def test_review_cultivate_live_no_pick() -> None:
    from types import SimpleNamespace
    from cultivate import _cultivate_inner

    called = {"generate": 0, "pick": 0}

    def fake_generate(*a, **k):
        called["generate"] += 1
        return "live review Q"

    def fake_pick(*a, **k):
        called["pick"] += 1
        return {"id": 1, "question": "bank Q"}

    decision = SimpleNamespace(
        type="review", difficulty="medium", reason="极限", ability_goal="compute"
    )
    with patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
         patch("cultivate.decide", return_value=decision), \
         patch("cultivate.generate", side_effect=fake_generate), \
         patch("cultivate.record"), \
         patch("cultivate.deliver", return_value=True), \
         patch("cultivate._save_last_push"), \
         patch("learner.item_bank.pick_for_push", side_effect=fake_pick), \
         patch("learner.item_bank.pick_for_push_walk", side_effect=fake_pick):
        _cultivate_inner("review")
    check(called["generate"] == 1, f"review must live generate {called}")
    check(called["pick"] == 0, f"review must not pick bank {called}")


def test_agent_review_live_no_pick() -> None:
    from types import SimpleNamespace
    from agent.tools import generate_question

    called = {"generate": 0, "pick": 0}

    def fake_generate(*a, **k):
        called["generate"] += 1
        return "agent live review"

    def fake_pick(*a, **k):
        called["pick"] += 1
        return {"id": 1, "question": "bank Q"}

    decision = SimpleNamespace(
        type="review", difficulty="medium", reason="极限",
        ability_goal="compute", priority=3,
    )
    with patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
         patch("cultivate.decide", return_value=decision), \
         patch("cultivate.generate", side_effect=fake_generate), \
         patch("cultivate.record"), \
         patch("cultivate.get_last_answer", return_value="A"), \
         patch("cultivate._last_ref_source", ""), \
         patch("cultivate._save_last_push"), \
         patch("cultivate._bkt_available", True), \
         patch("learner.item_bank.pick_for_push", side_effect=fake_pick), \
         patch("learner.item_bank.pick_technique_for_kp", return_value="t"):
        out = generate_question("review")
    check(out == "agent live review", f"agent review live {out!r}")
    check(called["generate"] == 1, f"agent review generate {called}")
    check(called["pick"] == 0, f"agent review no pick {called}")


def test_pick_rejects_pending_poor_and_sanitizes_stored_ref() -> None:
    """回归：pending/poor 不得抽；存量串科标签要清掉。"""
    from learner.db import Store
    from learner.item_bank import pick_for_push
    from cultivate_bank import sanitize_stored_ref_sources

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
        cdps = [
            {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
            {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
        ]
        pending = store.insert_bank_item(
            subject="math", question="pending题", answer="1", kp="极限",
            techniques=["t"], solution=sol, cdps=cdps,
        )
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store):
            check(pick_for_push("math", kp="极限") is None, "pick_for_push skips pending")
        _mark_pass(store, pending)
        poor = store.insert_bank_item(
            subject="math", question="poor题", answer="1", kp="极限",
            techniques=["t"], solution=sol, cdps=cdps,
        )
        store.apply_judge_verdict(poor, verdict="fail", reasons=["x"], confidence=1.0)
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store):
            hit = pick_for_push("math", kp="极限")
        check(hit and int(hit["id"]) == pending, "pick_for_push only pass not poor")

        comm = store.insert_bank_item(
            subject="comm",
            question="通信题串科源",
            answer="1",
            kp="随机过程",
            ref_source="2024年数学一",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "comm"},
        )
        math_ok = store.insert_bank_item(
            subject="math",
            question="数学题正确源",
            answer="1",
            kp="极限",
            ref_source="2023年数学一",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "math"},
        )
        r = sanitize_stored_ref_sources(store)
        check(r.get("cleared") >= 1, f"cleared mismatched refs ({r})")
        check((store.get_item(comm).get("ref_source") or "") == "", "comm dropped 数学一 tag")
        check((store.get_item(math_ok).get("ref_source") or "") == "2023年数学一", "matching tag kept")


def test_review_walk_uses_next_stocked_kp() -> None:
    """review 第一薄弱点无库存时，按序走到有 pass 的 KP；数学 walk 不抽 review 科目库存。"""
    from learner.db import Store
    from learner.item_bank import pick_for_push, pick_for_push_walk

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
        cdps = [
            {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
            {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
        ]
        rid = store.insert_bank_item(
            subject="review",
            question="复习极限题",
            answer="1",
            kp="函数极限与连续",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "math"},
        )
        _mark_pass(store, rid)

        def fake_ranked(subject, limit=8):
            if subject == "comm":
                return [("循环码与CRC", 3.8), ("M进制调制MASK/MPSK/MQAM", 2.3)]
            return [("数字特征", 1.8)]

        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked):
            check(
                pick_for_push("review", kp="循环码与CRC") is None,
                "hard filter still empty on CRC with only calc pass",
            )
            hit = pick_for_push_walk("review", kp="循环码与CRC")
            check(hit and int(hit["id"]) == rid, "review walk lands on stocked 函数极限")
            check(
                pick_for_push_walk("math", kp="循环码与CRC") is None,
                "math walk stays inside math stock",
            )


def test_comm_walk_uses_stocked_pass() -> None:
    """comm 首选 KP 无 pass 时走到通信库存；不串数学；不抽 pending/poor。"""
    from learner.db import Store
    from learner.item_bank import pick_for_push, pick_for_push_walk

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
        cdps = [
            {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
            {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
        ]
        comm_pass = store.insert_bank_item(
            subject="comm",
            question="随机过程题",
            answer="1",
            kp="随机过程",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "comm"},
        )
        _mark_pass(store, comm_pass)
        math_pass = store.insert_bank_item(
            subject="math",
            question="数学极限题",
            answer="1",
            kp="函数极限与连续",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "math"},
        )
        _mark_pass(store, math_pass)
        pending = store.insert_bank_item(
            subject="comm",
            question="pending PCM",
            answer="1",
            kp="PCM编码",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "comm"},
        )
        poor = store.insert_bank_item(
            subject="comm",
            question="poor QPSK",
            answer="1",
            kp="QPSK与OQPSK",
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": "comm"},
        )
        store.apply_judge_verdict(poor, verdict="fail", reasons=["x"], confidence=1.0)

        def fake_ranked(subject, limit=8):
            if subject == "comm":
                return [
                    ("线性分组码与汉明码", 4.0),
                    ("扰码与Rake", 3.0),
                    ("PCM编码", 2.0),
                    ("QPSK与OQPSK", 1.5),
                ]
            return [("函数极限与连续", 9.0)]

        prefer = "线性分组码与汉明码"
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked):
            check(
                pick_for_push("comm", kp=prefer) is None,
                "hard filter still empty on 汉明码 with only 随机过程 pass",
            )
            hit = pick_for_push_walk("comm", kp=prefer)
            check(
                hit and int(hit["id"]) == comm_pass,
                f"comm walk lands on stocked 随机过程 (got {hit})",
            )
            check((hit or {}).get("kp") == "随机过程", "comm walk stays on comm KP")
            hit_math = pick_for_push_walk("math", kp=prefer)
            check(
                hit_math and int(hit_math["id"]) == math_pass,
                f"math walk falls through to stocked math pass (got {hit_math})",
            )
            check(
                (hit_math or {}).get("kp") == "函数极限与连续",
                "math walk does not keep the empty comm prefer_kp",
            )
            check(
                pick_for_push_walk("comm", kp=prefer)
                and int(pick_for_push_walk("comm", kp=prefer)["id"]) != pending,
                "comm walk skips pending",
            )
            check(
                pick_for_push_walk("comm", kp=prefer)
                and int(pick_for_push_walk("comm", kp=prefer)["id"]) != poor,
                "comm walk skips poor",
            )
            check(
                pick_for_push_walk("comm", kp=prefer)
                and int(pick_for_push_walk("comm", kp=prefer)["id"]) != math_pass,
                "comm walk does not cross into math",
            )


def test_retired_pending_poor_quarantine_not_stock() -> None:
    """同 KP 仅 retired 旧 pass / pending / poor / quarantine 不算库存；ready+pass 才算。"""
    from learner.db import Store
    from learner.item_bank import select_gap_spec

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
        cdps = [
            {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
            {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
        ]

        def _item(q: str, kp: str = "极限") -> int:
            return store.insert_bank_item(
                subject="math", question=q, answer="1", kp=kp,
                techniques=["t"], solution=sol, cdps=cdps, status="ready",
            )

        retired = _item("retired former pass")
        _mark_pass(store, retired)
        store.record_push_for_item(item_id=retired, learner_id="u1", reason="极限")
        check((store.get_item(retired) or {}).get("status") == "retired", "push retires pass")
        check(store.count_ready("math", kp="极限") == 0, "retired pass not stock")

        pend = _item("pending only")
        check(store.count_ready("math", kp="极限") == 0, "pending not stock")

        poor = _item("poor only")
        store.apply_judge_verdict(poor, verdict="fail", reasons=["x"], confidence=1.0)
        check(store.count_ready("math", kp="极限") == 0, "poor not stock")

        qid = _item("quarantine former pass")
        _mark_pass(store, qid)
        store.quarantine_item(qid)
        check((store.get_item(qid) or {}).get("status") == "quarantine", "quarantined")
        check(store.count_ready("math", kp="极限") == 0, "quarantine not stock")

        ranked = [("极限", 4.0), ("幂级数与函数展开", 2.0)]
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", return_value=ranked), \
             patch("learner.item_bank.pick_technique_for_kp", return_value=""):
            spec = select_gap_spec("math")
        check(spec and spec.get("kp") == "极限", f"gap still wants KP with only retired pass {spec}")

        live = _item("live ready pass")
        _mark_pass(store, live)
        check(store.count_ready("math", kp="极限") == 1, "ready+pass is stock")
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", return_value=ranked), \
             patch("learner.item_bank.pick_technique_for_kp", return_value=""):
            spec2 = select_gap_spec("math")
        check(
            spec2 and spec2.get("kp") == "幂级数与函数展开",
            f"gap prefers unstocked KP over ready+pass {spec2}",
        )


def test_author_spec_drops_cross_subject_ref() -> None:
    from learner.db import Store
    from types import SimpleNamespace
    from cultivate_bank import _author_spec

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        decision = SimpleNamespace(
            type="push", difficulty="basic",
            reason="函数极限与连续 [l3=math.calc.limit.def] [ability=recognize]",
            ability_goal="recognize",
        )
        structured = {
            "techniques": ["t_a"],
            "solution": {"steps": [{"id": "s1", "text": "步骤"}],
                         "final_answer": "答案", "techniques_used": ["t_a"]},
            "cdps": [{"id": "c1", "prompt": "p", "expected": "e", "technique": "t_a", "depends_on": []},
                     {"id": "c2", "prompt": "p2", "expected": "e2", "technique": "t_a", "depends_on": ["c1"]}],
        }
        with patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("cultivate_bank.get_store", return_value=store), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", return_value="题干内容Y"), \
             patch("cultivate.get_last_answer", return_value="答案Y"), \
             patch("cultivate.get_last_ref_source", return_value="2024年通信原理"), \
             patch("cultivate.get_last_item_form", return_value="mcq"), \
             patch("cultivate._bkt_available", True), \
             patch("learner.kp_registry.pick_l3", return_value="math.calc.limit.def"), \
             patch("learner.kp_registry.list_l3_for_l2", return_value=[{"id": "x"}]), \
             patch("cultivate_bank.structure_item_via_llm", return_value=structured):
            spec = {"kp": "函数极限与连续", "technique": "t_a", "subject": "math"}
            r = _author_spec("math", spec)
        check(r.get("ok") is True, "author_spec ok with mismatched ref")
        it = store.get_item(r.get("item_id"))
        check(it and (it.get("ref_source") or "") == "", "mismatched 通信原理 dropped")


def test_math_slot_falls_through_empty_or_mastered_kp() -> None:
    """09:00 数学：prefer_kp 无 ready+pass，或该 KP 已掌握，仍抽其它数学 ready+pass。

    不打开 BANK_LIVE_FALLBACK。非「已掌握」的 defer 仍整槽跳过。
    """
    from types import SimpleNamespace
    from learner.context import bind_learner
    from learner.db import Store
    from learner.item_bank import pick_for_push, pick_for_push_walk
    import cultivate

    empty_kp = "特征值与特征向量"
    other_kp = "常微分方程"
    mastered_kp = "一元微分学（求导与作图）"
    sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
    cdps = [
        {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
        {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
    ]

    def _item(store, subject, question, kp):
        return store.insert_bank_item(
            subject=subject,
            question=question,
            answer="1",
            kp=kp,
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta={"content_subject": subject},
        )

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        pending = _item(store, "math", "特征值 pending", empty_kp)
        ode = _item(store, "math", "常微分方程题", other_kp)
        _mark_pass(store, ode)
        comm = _item(store, "comm", "通信题不应被数学 walk 抽到", "随机过程")
        _mark_pass(store, comm)

        def fake_ranked(subject, limit=8):
            if subject == "math":
                return [(empty_kp, 4.0), (other_kp, 2.0)]
            return [("随机过程", 3.0)]

        with patch.dict(os.environ, {"BANK_LIVE_FALLBACK": "0"}), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked):
            check(
                pick_for_push("math", kp=empty_kp) is None,
                "hard filter still empty when prefer_kp has no ready+pass",
            )
            hit = pick_for_push_walk("math", kp=empty_kp)
            check(
                hit and int(hit["id"]) == ode,
                f"empty prefer_kp walks to other math ready+pass (got {hit})",
            )
            check((hit or {}).get("kp") == other_kp, "walk lands on 常微分方程")
            check(int((hit or {}).get("id") or 0) != comm, "math walk does not enter comm")
            check(int((hit or {}).get("id") or 0) != pending, "walk skips pending")

        called = {"generate": 0}

        def fake_generate(*_a, **_k):
            called["generate"] += 1
            return "should-not-author"

        decision = SimpleNamespace(
            type="push",
            difficulty="intermediate",
            reason=f"{empty_kp}: 缺口 [ability=compute] [content_subject=math]",
            ability_goal="compute",
        )
        with patch.dict(os.environ, {"BANK_LIVE_FALLBACK": "0"}), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked), \
             patch("learner.item_bank.pick_technique_for_kp", return_value=""), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.deliver", return_value=True), \
             patch("cultivate._save_last_push"), \
             patch("cultivate._bkt_available", True), \
             patch("cultivate.DATA_DIR", td), \
             patch("cultivate.DAILY_RECORD_DIR", td):
            from cultivate import _cultivate_inner
            with bind_learner("staff1", binding="schedule"):
                _cultivate_inner("math")
        pushed = store._query("SELECT item_id FROM pushes ORDER BY id")
        check(called["generate"] == 0, "empty prefer_kp does not live-author")
        check(
            pushed and int(pushed[0]["item_id"]) == ode,
            f"cultivate delivers other math item (got {list(pushed)})",
        )

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        mastered_item = _item(store, "math", "求导已掌握仍有库存", mastered_kp)
        _mark_pass(store, mastered_item)
        other_item = _item(store, "math", "改抽微分方程", other_kp)
        _mark_pass(store, other_item)

        class _KC:
            def __init__(self, mastered: bool, p: float):
                self.is_mastered = mastered
                self.p_effective = p
                self.opportunity_count = 6 if mastered else 2

            def is_due(self):
                return False

        class _Log:
            def get_kp_mastery(self, _uid, kp):
                if kp == mastered_kp:
                    return _KC(True, 0.93)
                return _KC(False, 0.31)

            def get_all_kp_mastery(self, _uid):
                return {mastered_kp: 0.93, other_kp: 0.31}

        def fake_intervention(**kwargs):
            kp = kwargs.get("kp_name") or ""
            if kwargs.get("is_mastered"):
                return cultivate.InterventionDecision(
                    type="defer",
                    difficulty="basic",
                    reason=f"{kp}: 已掌握，无需干预",
                    priority=5,
                )
            return cultivate.InterventionDecision(
                type="push",
                difficulty="intermediate",
                reason=f"{kp}: 掌握度偏低，出题",
                priority=3,
            )

        weights = {"math": {"kp_weights": {mastered_kp: 5.0, other_kp: 1.0}}}

        def fake_ranked(subject, limit=8):
            return [(mastered_kp, 0.4), (other_kp, 2.5)]

        called = {"generate": 0}

        def fake_generate(*_a, **_k):
            called["generate"] += 1
            return "should-not-author"

        with patch.dict(os.environ, {"BANK_LIVE_FALLBACK": "0"}), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked), \
             patch("learner.item_bank.pick_technique_for_kp", return_value=""), \
             patch("cultivate.assess_state", return_value={"bkt_log": _Log()}), \
             patch("cultivate.decide_intervention", side_effect=fake_intervention), \
             patch("cultivate._load_weights", return_value=weights), \
             patch("cultivate._pick_kp_from_weights", return_value=mastered_kp), \
             patch("cultivate._uid", return_value="u1"), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.deliver", return_value=True), \
             patch("cultivate._save_last_push"), \
             patch("cultivate._bkt_available", True), \
             patch("cultivate.DATA_DIR", td), \
             patch("cultivate.DAILY_RECORD_DIR", td):
            from cultivate import _cultivate_inner
            with bind_learner("staff1", binding="schedule"):
                _cultivate_inner("math")
        pushed = store._query("SELECT item_id FROM pushes ORDER BY id")
        got = int(pushed[0]["item_id"]) if pushed else None
        check(called["generate"] == 0, "mastered prefer_kp does not live-author")
        check(got == other_item, f"mastered prefer_kp still pushes another math item (got {got})")
        check(got != mastered_item, "does not stay on the mastered KP item")

        other_defer = cultivate.InterventionDecision(
            type="defer",
            difficulty="basic",
            reason=f"{other_kp}: 无 L3 子知识点，跳过",
            priority=5,
        )
        check(
            not cultivate._is_mastered_defer(other_defer),
            "non-mastered defer is not treated as a mastered skip",
        )

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        stocked = _item(store, "math", "无 L3 时不应被抽走", other_kp)
        _mark_pass(store, stocked)
        called = {"generate": 0}

        def fake_generate(*_a, **_k):
            called["generate"] += 1
            return "nope"

        decision = SimpleNamespace(
            type="defer",
            difficulty="basic",
            reason=f"{other_kp}: 无 L3 子知识点，跳过",
            ability_goal="",
        )
        with patch.dict(os.environ, {"BANK_LIVE_FALLBACK": "0"}), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("cultivate.assess_state", return_value={"bkt_log": object()}), \
             patch("cultivate.decide", return_value=decision), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.deliver", return_value=True), \
             patch("cultivate._bkt_available", True):
            from cultivate import _cultivate_inner
            _cultivate_inner("math")
        pushed = store._query("SELECT item_id FROM pushes")
        check(not pushed and called["generate"] == 0, "non-mastered defer still skips the math slot")


def test_mastered_fallback_prefers_same_l1_textbook() -> None:
    """已掌握 prefer_kp：同 L1 ready+pass textbook_example 先于薄弱 KP / 非教材库存。

    来源只认 meta.source（item_source），不认 ref_source。没有同 L1 教材时仍走 #45。
    """
    from learner.context import bind_learner
    from learner.db import Store
    from learner.item_bank import pick_for_push_walk
    import cultivate

    mastered = "一元微分学（求导与作图）"  # calc
    text_kp = "微分中值定理与泰勒"  # calc
    walk_kp = "特征值与特征向量"  # linalg
    other_l1 = "二次型"  # linalg
    ref_kp = "函数极限与连续"  # calc
    ode = "常微分方程"  # calc
    sol = {"steps": [{"id": "s1", "text": "x"}], "final_answer": "1", "techniques_used": ["t"]}
    cdps = [
        {"id": "cdp1", "prompt": "a", "expected": "b", "technique": "t", "depends_on": []},
        {"id": "cdp2", "prompt": "c", "expected": "d", "technique": "t", "depends_on": []},
    ]

    def _item(store, question, kp, *, source="", ref_source="", quality=None):
        meta = {"content_subject": "math"}
        if source:
            meta["source"] = source
        iid = store.insert_bank_item(
            subject="math",
            question=question,
            answer="1",
            kp=kp,
            ref_source=ref_source,
            techniques=["t"],
            solution=sol,
            cdps=cdps,
            meta=meta,
        )
        _mark_pass(store, iid)
        if quality is not None:
            store._txn(lambda conn: conn.execute(
                "UPDATE items SET quality_score=? WHERE id=?",
                (float(quality), int(iid)),
            ))
        return iid

    def _mark_seen(store, item_id, learner_id="u-seen"):
        store._txn(lambda conn: conn.execute(
            """INSERT INTO pushes
               (item_id, learner_id, day, seq, pushed_at, slot, channel, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                int(item_id), learner_id, "2026-09-25", 1,
                "2026-09-25T01:00:00+00:00", "math", "push",
                "2026-09-25T01:00:00+00:00",
            ),
        ))

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        own_plain = _item(store, "求导普通题", mastered)
        own_tb = _item(
            store, "求导教材例题仍留在已掌握 KP", mastered,
            source="textbook_example", quality=1.0,
        )
        same_l1 = _item(
            store, "泰勒教材例题", text_kp,
            source="textbook_example", quality=0.2,
        )
        walk_item = _item(store, "特征值普通题", walk_kp, quality=1.0)
        other_tb = _item(
            store, "二次型教材例题不同 L1", other_l1,
            source="textbook_example", quality=1.0,
        )
        ref_only = _item(
            store, "极限只写了 ref_source", ref_kp,
            ref_source="textbook:puheping_math_contest_v2", quality=1.0,
        )
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store):
            hit = pick_for_push_walk("math", kp=walk_kp, mastered_from=mastered)
            check(
                hit and int(hit["id"]) == same_l1,
                f"same-L1 textbook wins over weak KP and higher scores (got {hit})",
            )
            check((hit or {}).get("kp") == text_kp, "winner is another calc KP")
            check(
                int((hit or {}).get("id") or 0) not in (own_plain, own_tb, walk_item, other_tb, ref_only),
                "does not stay on mastered KP, other L1, or ref_source-only",
            )
            check(
                ((hit or {}).get("meta") or {}).get("source") == "textbook_example",
                "winner meta.source is textbook_example",
            )
            bare = pick_for_push_walk("math", kp=walk_kp)
            check(
                bare and int(bare["id"]) == walk_item,
                f"without mastered_from, walk still takes the preferred KP (got {bare})",
            )
            _mark_seen(store, same_l1, "u-seen")
            seen = pick_for_push_walk(
                "math", kp=walk_kp, mastered_from=mastered, learner_id="u-seen",
            )
            check(
                seen and int(seen["id"]) == walk_item,
                f"seen same-L1 textbook falls through to #45 walk (got {seen})",
            )

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        ode_item = _item(store, "微分方程普通题", ode)
        _item(
            store, "特征值教材不在 calc", walk_kp,
            source="textbook_example", quality=1.0,
        )
        _item(
            store, "极限 ref_source 不是 meta.source", ref_kp,
            ref_source="textbook:puheping_math_contest_v2", quality=1.0,
        )
        pending = store.insert_bank_item(
            subject="math", question="泰勒 pending 教材", answer="1", kp=text_kp,
            techniques=["t"], solution=sol, cdps=cdps,
            meta={"content_subject": "math", "source": "textbook_example"},
        )
        with patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.db.get_store", return_value=store):
            hit = pick_for_push_walk("math", kp=ode, mastered_from=mastered)
            check(
                hit and int(hit["id"]) == ode_item,
                f"no same-L1 textbook keeps #45 L2/walk (got {hit})",
            )
            check(int((hit or {}).get("id") or 0) != pending, "pending textbook is not stock")

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "t.db"))
        _item(store, "求导普通题", mastered)
        _item(
            store, "求导教材例题仍留在已掌握 KP", mastered,
            source="textbook_example", quality=1.0,
        )
        same_l1 = _item(
            store, "泰勒教材例题", text_kp,
            source="textbook_example", quality=0.2,
        )
        walk_item = _item(store, "特征值普通题", walk_kp, quality=1.0)
        _item(
            store, "二次型教材例题不同 L1", other_l1,
            source="textbook_example", quality=1.0,
        )

        class _KC:
            def __init__(self, mastered_flag: bool, p: float):
                self.is_mastered = mastered_flag
                self.p_effective = p
                self.opportunity_count = 6 if mastered_flag else 2

            def is_due(self):
                return False

        class _Log:
            def get_kp_mastery(self, _uid, kp):
                if kp == mastered:
                    return _KC(True, 0.93)
                return _KC(False, 0.31)

            def get_all_kp_mastery(self, _uid):
                return {mastered: 0.93, walk_kp: 0.31, text_kp: 0.4}

        def fake_intervention(**kwargs):
            kp = kwargs.get("kp_name") or ""
            if kwargs.get("is_mastered"):
                return cultivate.InterventionDecision(
                    type="defer",
                    difficulty="basic",
                    reason=f"{kp}: 已掌握，无需干预",
                    priority=5,
                )
            return cultivate.InterventionDecision(
                type="push",
                difficulty="intermediate",
                reason=f"{kp}: 掌握度偏低，出题",
                priority=3,
            )

        weights = {"math": {"kp_weights": {mastered: 5.0, walk_kp: 3.0, text_kp: 0.2}}}

        def fake_ranked(subject, limit=8):
            return [(mastered, 0.2), (walk_kp, 4.0), (text_kp, 0.1)]

        called = {"generate": 0}

        def fake_generate(*_a, **_k):
            called["generate"] += 1
            return "should-not-author"

        with patch.dict(os.environ, {"BANK_LIVE_FALLBACK": "0"}), \
             patch("learner.db.get_store", return_value=store), \
             patch("learner.item_bank.get_store", return_value=store), \
             patch("learner.item_bank.weak_kp_ranked", side_effect=fake_ranked), \
             patch("learner.item_bank.pick_technique_for_kp", return_value=""), \
             patch("cultivate.assess_state", return_value={"bkt_log": _Log()}), \
             patch("cultivate.decide_intervention", side_effect=fake_intervention), \
             patch("cultivate._load_weights", return_value=weights), \
             patch("cultivate._pick_kp_from_weights", return_value=mastered), \
             patch("cultivate._uid", return_value="u1"), \
             patch("cultivate.generate", side_effect=fake_generate), \
             patch("cultivate.deliver", return_value=True), \
             patch("cultivate._save_last_push"), \
             patch("cultivate._bkt_available", True), \
             patch("cultivate.DATA_DIR", td), \
             patch("cultivate.DAILY_RECORD_DIR", td):
            from cultivate import _cultivate_inner
            with bind_learner("staff1", binding="schedule"):
                _cultivate_inner("math")
        pushed = store._query("SELECT item_id FROM pushes ORDER BY id")
        got = int(pushed[0]["item_id"]) if pushed else None
        check(called["generate"] == 0, "textbook fallback does not live-author")
        check(got == same_l1, f"cultivate mastered slot draws same-L1 textbook (got {got})")
        check(got != walk_item, "does not fall through to the weak KP while textbook exists")


def main() -> int:
    print("== item bank / CDP unit ==")
    _ensure_cultivate_deps()
    test_schema_and_pick()
    test_cultivate_uses_bank_no_author()
    test_author_spec_inserts_ready()
    test_author_spec_keeps_explain_type()
    test_author_spec_drops_cross_subject_ref()
    test_pregen_fallback_next_gap()
    test_offpeak_slots_and_ref_gate()
    test_review_pregen_and_fill_skip()
    test_review_cultivate_live_no_pick()
    test_agent_review_live_no_pick()
    test_pick_rejects_pending_poor_and_sanitizes_stored_ref()
    test_review_walk_uses_next_stocked_kp()
    test_comm_walk_uses_stocked_pass()
    test_retired_pending_poor_quarantine_not_stock()
    test_math_slot_falls_through_empty_or_mastered_kp()
    test_mastered_fallback_prefers_same_l1_textbook()
    print("=" * 40)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL ITEM BANK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
