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

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


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
        check(store.count_ready("math") == 1, "ready count 1")
        check(store.count_ready("math", kp="极限", technique="t_a") == 1, "ready by tech")

        # second item different kp
        store.insert_bank_item(
            subject="math",
            question="级数题干乙",
            answer="1",
            kp="幂级数与函数展开",
            techniques=["series"],
            solution=sol,
            cdps=cdps,
            status="ready",
        )

        hit = store.pick_ready_item(subject="math", kp="极限", technique="t_a")
        check(hit and hit["kp"] == "极限", "pick KP+tech")
        hit2 = store.pick_ready_item(subject="math", kp="不存在的KP")
        check(hit2 is not None and hit2.get("subject") == "math", "pick widens to any ready")

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
             patch("learner.item_bank.pick_technique_for_kp", return_value="t"):
            from cultivate import _cultivate_inner
            with bind_learner("staff1", binding="schedule"):
                _cultivate_inner("math")
        check(called["generate"] == 0, "cultivate bank path zero author")
        check(store.count_rows("pushes") == 1, "cultivate created push")


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
             patch("cultivate._last_ref_source", ""), \
             patch("cultivate._last_item_form", ""), \
             patch("cultivate._bkt_available", True), \
             patch("learner.kp_registry.pick_l3", return_value="math.calc.limit.def"), \
             patch("learner.kp_registry.list_l3_for_l2", return_value=[{"id": "x"}]), \
             patch("cultivate_bank.structure_item_via_llm", return_value=structured):
            spec = {"kp": "函数极限与连续", "technique": "t_a", "subject": "math"}
            r = _author_spec("math", spec)
        check(r.get("ok") is True, "author_spec ok")
        check(store.count_ready("math") == 1, "item inserted ready")


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


def main() -> int:
    print("== item bank / CDP unit ==")
    test_schema_and_pick()
    test_cultivate_uses_bank_no_author()
    test_author_spec_inserts_ready()
    test_pregen_fallback_next_gap()
    print("=" * 40)
    if _fails:
        print(f"DONE with {_fails} FAIL(s)")
        return 1
    print("ALL ITEM BANK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
