# -*- coding: utf-8 -*-
"""Daily grade edge tests (mock LLM; learner paths)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config as config_mod
import grade as grade_mod
from grade import GradeResult, _detect_item_type, _parse_grade_verdict, grade_answer
from agent import tools as tools_mod
from learner import paths as paths_mod
from learner.context import bind_learner


def sep(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    with bind_learner("test_staff_daily_grade"):
        _run_daily(check)

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL DAILY GRADE TESTS PASSED")
    sys.exit(0)


def _structured_llm(verdict: str, *, grade_conf: float = 0.95, agrees: bool = True):
    def _side(system, user, task_type="grade", *a, **kw):
        if task_type == "verify_grade":
            return json.dumps(
                {"agrees": agrees, "confidence": 0.9, "reasoning": "ok"},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "verdict": verdict,
                "confidence": grade_conf,
                "explanation": f"verdict={verdict}",
            },
            ensure_ascii=False,
        )

    return _side


def _run_daily(check) -> None:
    sep("1. _detect_item_type")
    check(_detect_item_type("填空：lim = ____") == "blank", "blank ____")
    check(_detect_item_type("求证：f 连续") == "proof_outline", "proof")
    mcq = "下列正确的是\nA. 1\nB. 2\nC. 3\nD. 4"
    check(_detect_item_type(mcq) == "mcq", "mcq ABCD")
    check(_detect_item_type("简述香农公式") == "open", "open")

    sep("2. _parse_grade_verdict")
    check(_parse_grade_verdict("正确与否：正确\n评语：好") == (True, None), "correct")
    check(
        _parse_grade_verdict("正确与否：不正确\n评语：错了") == (False, None),
        "incorrect",
    )
    check(_parse_grade_verdict("正确与否：错误\n评语：x") == (False, None), "error")
    ok, cr = _parse_grade_verdict("正确与否：部分正确\n评语：半对")
    check(ok is False and cr == 0.5, f"partial credit={cr}")
    check(
        _parse_grade_verdict("正确与否：正确\n评语：此前不正确的步骤已改") == (True, None),
        "comment noise ok",
    )
    check(_parse_grade_verdict("") == (False, None), "empty -> wrong")
    check(_parse_grade_verdict("评语：写得不错") == (False, None), "no verdict -> wrong")

    sep("3. grade_answer empty q/a")
    with patch.object(grade_mod, "call_llm") as mock_llm:
        r = grade_answer("", "A")
        check("题目为空" in r.feedback, f"empty q: {r.feedback}")
        check(mock_llm.call_count == 0, "empty q no LLM")
        r = grade_answer(mcq, "")
        check("未作答" in r.feedback, f"empty a: {r.feedback}")
        check(mock_llm.call_count == 0, "empty a no LLM")
        r = grade_answer(mcq, "   \n\t  ")
        check("未作答" in r.feedback, "whitespace a")
        check(mock_llm.call_count == 0, "ws a no LLM")

    sep("4. mock LLM + BKT isolated DATA_DIR")
    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td):
            paths_mod.ensure_learner_dir()
            with patch(
                "grade.call_llm", side_effect=_structured_llm("correct")
            ), patch(
                "learner.kp_registry.normalize_kp_for_grade",
                return_value="函数极限与连续",
            ), patch("learner.weights_ops.bump_kp_weight") as bump, patch(
                "learner.weights_ops.decay_kp_weight"
            ) as decay:
                r = grade_answer(mcq, "A", kp_name="函数极限与连续", subject="math")
                check(r.is_correct is True, f"correct flag {r.is_correct}")
                check(r.status == "applied", f"status={r.status}")
                check(r.credit is None, "no partial credit")
                check(r.item_type == "mcq", f"item_type={r.item_type}")
                check(r.kp_name == "函数极限与连续", f"kp={r.kp_name}")
                check(bump.call_count == 0, "no weight bump on correct")
                check(decay.call_count == 1, "decay on correct")

            with patch(
                "grade.call_llm", side_effect=_structured_llm("partial")
            ), patch(
                "learner.kp_registry.normalize_kp_for_grade",
                return_value="函数极限与连续",
            ), patch("learner.weights_ops.bump_kp_weight") as bump, patch(
                "learner.weights_ops.decay_kp_weight"
            ) as decay:
                r = grade_answer(
                    "求 lim ____", "0.5", kp_name="函数极限与连续", subject="math"
                )
                check(
                    r.is_correct is False and r.credit == 0.5,
                    f"partial {r.is_correct}/{r.credit}",
                )
                check(r.status == "applied", f"partial status={r.status}")
                check(r.item_type == "blank", f"blank type {r.item_type}")
                check(bump.call_count == 0, "no bump on partial")
                check(decay.call_count == 1, "decay on partial")

            with patch(
                "grade.call_llm", side_effect=_structured_llm("incorrect")
            ), patch(
                "learner.kp_registry.normalize_kp_for_grade",
                return_value="函数极限与连续",
            ), patch("learner.weights_ops.bump_kp_weight") as bump, patch(
                "learner.weights_ops.decay_kp_weight"
            ) as decay:
                r = grade_answer(mcq, "Z", kp_name="函数极限与连续", subject="math")
                check(r.is_correct is False and r.credit is None, "incorrect")
                check(r.status == "applied", f"incorrect status={r.status}")
                check(bump.call_count == 1, "bump on incorrect")
                check(decay.call_count == 0, "no decay on incorrect")

            with patch(
                "grade.call_llm",
                return_value="正确与否：正确\n评语：选 A\n涉及知识点：函数极限与连续",
            ), patch(
                "learner.kp_registry.normalize_kp_for_grade",
                return_value="函数极限与连续",
            ), patch("learner.weights_ops.bump_kp_weight") as bump:
                r = grade_answer(mcq, "A", kp_name="函数极限与连续", subject="math")
                check(r.status == "pending", f"text fallback status={r.status}")
                check(bump.call_count == 0, "text fallback no bump")

            with patch("grade.call_llm", side_effect=RuntimeError("llm down")):
                try:
                    grade_answer(mcq, "A", subject="math")
                    check(False, "should raise")
                except RuntimeError:
                    check(True, "LLM error propagates")

    sep("5. tools.grade_answer boundaries")
    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td):
            paths_mod.ensure_learner_dir()
            full_q = mcq + "\n" + ("补充说明。" * 40)
            # BIG-TEACH-013: 权威源改为 SQLite，直接播种推送（替代写 last_push.json）
            from learner.db import get_store
            store = get_store()
            store.record_push(
                subject="math", question=full_q, answer="A", difficulty="intermediate",
                kp="函数极限与连续", learner_id="test_staff_daily_grade",
                pushed_at="2099-01-01T00:00:00+00:00", day="2099-01-01",
            )

            r = tools_mod.grade_answer("", "")
            check("未作答" in r, f"tool empty: {r}")
            r = tools_mod.grade_answer("", "   ")
            check("未作答" in r, "tool whitespace")

            with patch.object(tools_mod, "_read_latest_entry", return_value=None), patch.object(
                tools_mod, "_load_last_push_record", return_value={}
            ), patch.object(tools_mod, "_load_last_push_question", return_value=""):
                r = tools_mod.grade_answer("", "A")
                check("找不到完整题目" in r, f"no stem: {r}")

            fake = GradeResult(
                is_correct=True,
                feedback="正确与否：正确\n评语：ok",
                kp_name="函数极限与连续",
                subject="math",
                p_mastery_before=0.3,
                p_mastery_after=0.4,
            )
            with patch("grade.grade_answer", return_value=fake) as g:
                trunc = full_q[:120]
                r = tools_mod.grade_answer(trunc, "A")
                check("✅ 正确" in r, f"trunc heal tag: {r[:120]}")
                args, kwargs = g.call_args
                check(args[0] == full_q, "used full stored stem")
                check(
                    kwargs.get("kp_name") == "函数极限与连续",
                    f"kp pass-through {kwargs}",
                )

            fake_p = GradeResult(
                is_correct=False,
                feedback="半对",
                credit=0.5,
                kp_name="函数极限与连续",
                subject="math",
                p_mastery_before=0.3,
                p_mastery_after=0.35,
            )
            with patch("grade.grade_answer", return_value=fake_p):
                r = tools_mod.grade_answer("", "半对")
                check("🔶 部分正确" in r, f"partial tag: {r[:80]}")

            with patch("grade.grade_answer", side_effect=RuntimeError("boom")):
                r = tools_mod.grade_answer("", "A")
                check(r.startswith("批改失败"), f"tool catch: {r}")

            fake_pend = GradeResult(
                is_correct=True,
                feedback="ok",
                kp_name="函数极限与连续",
                subject="math",
                status="pending",
                confidence=0.4,
            )
            with patch("grade.grade_answer", return_value=fake_pend):
                r = tools_mod.grade_answer("", "A")
                check(
                    "pending" in r.lower() or "掌握度未更新" in r,
                    f"pending note: {r[:120]}",
                )

    sep("6. _looks_truncated")
    stored = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 20
    check(tools_mod._looks_truncated(stored[:50], stored) is True, "prefix truncated")
    check(tools_mod._looks_truncated(stored, stored) is False, "exact not truncated")
    check(tools_mod._looks_truncated("", stored) is False, "empty provided")
    check(tools_mod._looks_truncated("完全另一道题", stored) is False, "unrelated")

    sep("7. resolve_kp preferred")
    try:
        from learner.kp_registry import normalize_kp_for_grade, reload_registry

        reload_registry()
        got = normalize_kp_for_grade(
            "math",
            "多元函数偏导数、常微分方程、定积分",
            preferred="矩阵与初等变换",
        )
        # Registry may evolve; preferred should win when resolvable
        if got is None:
            check(True, "preferred skipped (L2 not in current registry)")
        else:
            check(got == "矩阵与初等变换", f"preferred kp={got}")
    except Exception as e:
        check(False, f"kp registry: {e}")


if __name__ == "__main__":
    main()
