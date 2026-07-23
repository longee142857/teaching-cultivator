# -*- coding: utf-8 -*-
"""日常批改边界测试（grade.py + agent.tools.grade_answer，默认 mock LLM）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import grade as grade_mod
from grade import GradeResult, _detect_item_type, _parse_grade_verdict, grade_answer
from agent import tools as tools_mod


def sep(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    # ── 纯函数：题型 / 判词 ──────────────────────────────
    sep("1. _detect_item_type")
    check(_detect_item_type("填空：lim = ____") == "blank", "blank ____")
    check(_detect_item_type("求证：f 连续") == "proof_outline", "proof 求证")
    mcq = "下列正确的是\nA. 1\nB. 2\nC. 3\nD. 4"
    check(_detect_item_type(mcq) == "mcq", "mcq ABCD")
    check(_detect_item_type("简述香农公式") == "open", "open")

    sep("2. _parse_grade_verdict")
    check(
        _parse_grade_verdict("正确与否：正确\n评语：好") == (True, None),
        "正确",
    )
    check(
        _parse_grade_verdict("正确与否：不正确\n评语：错了") == (False, None),
        "不正确 ≠ 正确",
    )
    check(
        _parse_grade_verdict("正确与否：错误\n评语：x") == (False, None),
        "错误",
    )
    ok, cr = _parse_grade_verdict("正确与否：部分正确\n评语：半对")
    check(ok is False and cr == 0.5, f"部分正确 credit={cr}")
    # 评语里提「不正确」但首行判对 → 仍应对
    check(
        _parse_grade_verdict("正确与否：正确\n评语：此前不正确的步骤已改") == (True, None),
        "评语含不正确不误伤",
    )
    check(_parse_grade_verdict("") == (False, None), "空 LLM → 判错")
    check(_parse_grade_verdict("评语：写得不错") == (False, None), "无 verdict → 判错")

    # ── grade_answer 早退（不调 LLM）─────────────────────
    sep("3. grade_answer 空题干 / 空作答")
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

    sep("4. mock LLM 正确 / 部分 / 错误 + BKT 隔离目录")
    with tempfile.TemporaryDirectory() as td:
        with patch.object(grade_mod, "DATA_DIR", td), patch(
            "grade.call_llm",
            return_value="正确与否：正确\n评语：选 A\n涉及知识点：函数极限与连续",
        ), patch(
            "learner.kp_registry.normalize_kp_for_grade",
            return_value="函数极限与连续",
        ), patch(
            "learner.weights_ops.bump_kp_weight"
        ) as bump:
            r = grade_answer(mcq, "A", kp_name="函数极限与连续", subject="math")
            check(r.is_correct is True, f"correct flag {r.is_correct}")
            check(r.credit is None, "no partial credit")
            check(r.item_type == "mcq", f"item_type={r.item_type}")
            check(r.kp_name == "函数极限与连续", f"kp={r.kp_name}")
            check(bump.call_count == 0, "no weight bump on correct")

        with patch.object(grade_mod, "DATA_DIR", td), patch(
            "grade.call_llm",
            return_value="正确与否：部分正确\n评语：思路对答案错\n涉及知识点：极限",
        ), patch(
            "learner.kp_registry.normalize_kp_for_grade",
            return_value="函数极限与连续",
        ), patch("learner.weights_ops.bump_kp_weight") as bump:
            r = grade_answer("求 lim ____", "0.5", kp_name="函数极限与连续", subject="math")
            check(r.is_correct is False and r.credit == 0.5, f"partial {r.is_correct}/{r.credit}")
            check(r.item_type == "blank", f"blank type {r.item_type}")
            check(bump.call_count == 0, "no bump on partial")

        with patch.object(grade_mod, "DATA_DIR", td), patch(
            "grade.call_llm",
            return_value="正确与否：不正确\n评语：错\n涉及知识点：极限",
        ), patch(
            "learner.kp_registry.normalize_kp_for_grade",
            return_value="函数极限与连续",
        ), patch("learner.weights_ops.bump_kp_weight") as bump:
            r = grade_answer(mcq, "Z", kp_name="函数极限与连续", subject="math")
            check(r.is_correct is False and r.credit is None, "incorrect")
            check(bump.call_count == 1, "bump on incorrect")

        with patch.object(grade_mod, "DATA_DIR", td), patch(
            "grade.call_llm", side_effect=RuntimeError("llm down")
        ):
            try:
                grade_answer(mcq, "A", subject="math")
                check(False, "should raise")
            except RuntimeError:
                check(True, "LLM error propagates to tools layer")

    # ── tools.grade_answer：last_push / 截断 / 空 ─────────
    sep("5. tools.grade_answer 边界")
    with tempfile.TemporaryDirectory() as td:
        full_q = mcq + "\n" + ("补充说明。" * 40)
        lp = {
            "subject": "math",
            "question": full_q,
            "answer": "A",
            "kp": "函数极限与连续",
            "timestamp": "2099-01-01T00:00:00",
        }
        with open(os.path.join(td, "last_push.json"), "w", encoding="utf-8") as f:
            json.dump(lp, f, ensure_ascii=False)

        with patch.object(tools_mod, "DATA_DIR", td):
            r = tools_mod.grade_answer("", "")
            check("未作答" in r, f"tool empty: {r}")
            r = tools_mod.grade_answer("", "   ")
            check("未作答" in r, "tool whitespace")

        # 无 last_push、无 latest
        with tempfile.TemporaryDirectory() as td2:
            with patch.object(tools_mod, "DATA_DIR", td2), patch.object(
                tools_mod, "_read_latest_entry", return_value=None
            ):
                r = tools_mod.grade_answer("", "A")
                check("找不到完整题目" in r, f"no stem: {r}")

        # 截断前缀 → 用全文；mock grade
        fake = GradeResult(
            is_correct=True,
            feedback="正确与否：正确\n评语：ok",
            kp_name="函数极限与连续",
            subject="math",
            p_mastery_before=0.3,
            p_mastery_after=0.4,
        )
        with patch.object(tools_mod, "DATA_DIR", td), patch(
            "grade.grade_answer", return_value=fake
        ) as g:
            trunc = full_q[:120]
            r = tools_mod.grade_answer(trunc, "A")
            check("✅ 正确" in r, f"trunc heal tag: {r[:120]}")
            args, kwargs = g.call_args
            check(args[0] == full_q, "used full stored stem")
            check(kwargs.get("kp_name") == "函数极限与连续", f"kp pass-through {kwargs}")

        # 部分正确 tag
        fake_p = GradeResult(
            is_correct=False,
            feedback="正确与否：部分正确\n评语：半",
            kp_name="函数极限与连续",
            subject="math",
            credit=0.5,
            p_mastery_before=0.3,
            p_mastery_after=0.35,
        )
        with patch.object(tools_mod, "DATA_DIR", td), patch(
            "grade.grade_answer", return_value=fake_p
        ):
            r = tools_mod.grade_answer("", "半对")
            check("🔶 部分正确" in r, f"partial tag: {r[:80]}")

        with patch.object(tools_mod, "DATA_DIR", td), patch(
            "grade.grade_answer", side_effect=RuntimeError("boom")
        ):
            r = tools_mod.grade_answer("", "A")
            check(r.startswith("批改失败"), f"tool catch: {r}")

    sep("6. _looks_truncated")
    stored = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 20
    check(tools_mod._looks_truncated(stored[:50], stored) is True, "prefix truncated")
    check(tools_mod._looks_truncated(stored, stored) is False, "exact not truncated")
    check(tools_mod._looks_truncated("", stored) is False, "empty provided")
    check(tools_mod._looks_truncated("完全另一道题", stored) is False, "unrelated")

    sep("7. resolve_kp 批改 preferred（既有脚本）")
    try:
        from learner.kp_registry import normalize_kp_for_grade, reload_registry

        reload_registry()
        got = normalize_kp_for_grade(
            "math",
            "多元函数偏导数、常微分方程、定积分",
            preferred="矩阵与初等变换",
        )
        check(got == "矩阵与初等变换", f"preferred kp={got}")
    except Exception as e:
        check(False, f"kp registry: {e}")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL DAILY GRADE EDGE TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
