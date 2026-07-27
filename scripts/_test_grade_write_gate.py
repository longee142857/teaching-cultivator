# -*- coding: utf-8 -*-
"""BIG-TEACH-012a #7a: 批改写入闸测试（grade write gate，mock LLM）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config as config_mod
import grade as grade_mod
from grade import GradeResult, grade_answer, _parse_grade_json, _compute_effective_confidence, CONFIDENCE_THRESHOLD


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

    mcq = "下列正确的是\nA. 1\nB. 2\nC. 3\nD. 4"

    # ── 1. Confident + agrees → applied ──
    sep("1. Confident grade + verifier agrees → applied, BKT updated")
    with patch("grade._call_grade_llm") as mock_g, \
         patch("grade._call_verify_llm") as mock_v, \
         patch("grade._get_bkt_log") as mock_bkt:

        mock_g.return_value = {"verdict": "correct", "confidence": 0.95, "raw": "正确与否：正确\n评语：好"}
        mock_v.return_value = {"agrees": True, "confidence": 0.90, "reasoning": "agree"}

        fake_bkt = MagicMock()
        fake_bkt.get_kp_mastery.return_value = None
        mock_bkt.return_value = fake_bkt

        r = grade_answer(mcq, "A", kp_name="函数极限与连续", subject="math")
        check(r.status == "applied", f"status={r.status}")
        check(r.is_correct is True, f"correct={r.is_correct}")
        check(r.confidence >= CONFIDENCE_THRESHOLD, f"confidence={r.confidence}")
        check(fake_bkt.record.called, "BKT.record called")

    # ── 2. Low confidence → pending ──
    sep("2. Low confidence → pending, BKT not updated")
    with patch("grade._call_grade_llm") as mock_g, \
         patch("grade._call_verify_llm") as mock_v, \
         patch("grade._get_bkt_log") as mock_bkt:

        mock_g.return_value = {"verdict": "incorrect", "confidence": 0.3, "raw": "错误", "from_fallback": False}
        mock_v.return_value = {"agrees": True, "confidence": 0.3, "reasoning": "unsure", "from_fallback": False}

        fake_bkt = MagicMock()
        fake_bkt.get_kp_mastery.return_value = None
        mock_bkt.return_value = fake_bkt

        with tempfile.TemporaryDirectory() as td:
            with patch.object(config_mod, "DATA_DIR", td):
                r = grade_answer(mcq, "Z", kp_name="函数极限与连续", subject="math")
        check(r.status == "pending", f"status={r.status}")
        check(r.is_correct is False, f"correct={r.is_correct}")
        check(not fake_bkt.record.called, "BKT.record NOT called")

        # GradeResult still reports the verdict even when pending
        check(r.kp_name == "函数极限与连续", f"kp={r.kp_name}")

    # ── 3. Verifier disagrees → pending ──
    sep("3. Verifier disagrees → pending")
    with patch("grade._call_grade_llm") as mock_g, \
         patch("grade._call_verify_llm") as mock_v, \
         patch("grade._get_bkt_log") as mock_bkt:

        mock_g.return_value = {"verdict": "correct", "confidence": 0.95, "raw": "正确", "from_fallback": False}
        mock_v.return_value = {"agrees": False, "confidence": 0.85, "reasoning": "grader was wrong", "from_fallback": False}

        fake_bkt = MagicMock()
        fake_bkt.get_kp_mastery.return_value = None
        mock_bkt.return_value = fake_bkt

        with tempfile.TemporaryDirectory() as td:
            with patch.object(config_mod, "DATA_DIR", td):
                r = grade_answer(mcq, "B", kp_name="函数极限与连续", subject="math")
        check(r.status == "pending", f"disagree status={r.status}")
        check(not fake_bkt.record.called, "BKT.record NOT called on disagree")

    # ── 4. override_grade ──
    sep("4. override_grade")
    from agent import tools as tools_mod
    from bkt import KCState

    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "answer-log.jsonl")
        kc = KCState()
        kc.update(False, item_type="mcq", force=True)
        wrong_state = kc.to_dict()
        entry1 = {
            "ts": "2026-01-01T00:00:00+00:00", "user_id": "wx_123",
            "knowledge_point": "极限", "correct": False, "item_type": "mcq",
            "mastery_before": 0.2, "mastery_after": round(kc.p_mastery, 4),
            "update_applied": True, "status": "applied", "state": wrong_state,
        }
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(entry1, ensure_ascii=False) + "\n")

        with patch.object(config_mod, "DATA_DIR", td):
            result = tools_mod.override_grade("极限", True, subject="math")
            check("已覆盖" in result, f"override msg: {result[:100]}")

            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            last = json.loads(lines[-1])
            check(last.get("status") == "overridden", f"status={last.get('status')}")
            check(last.get("correct") is True, f"correct={last.get('correct')}")
            check(
                last.get("supersedes_ts") == "2026-01-01T00:00:00+00:00",
                f"supersedes={last.get('supersedes_ts')}",
            )
            check(last.get("update_applied") is True, "override applied once")
            # opportunity: only the corrected update (wrong row superseded)
            check(
                last.get("state", {}).get("opportunity_count") == 1,
                f"opp={last.get('state', {}).get('opportunity_count')} (no double-count)",
            )

    # ── 5. _parse_grade_json ──
    sep("5. _parse_grade_json")
    r1 = _parse_grade_json('{"verdict": "correct", "confidence": 0.9}')
    check(r1 is not None and r1["verdict"] == "correct", "valid JSON")

    r2 = _parse_grade_json("正确与否：正确\n评语：好")
    check(r2 is None, "text-only → None")

    r3 = _parse_grade_json('{"verdict": "maybe", "confidence": 0.5}')
    check(r3 is None, "invalid verdict → None")

    r4 = _parse_grade_json("无意义文本")
    check(r4 is None, "garbage → None")

    # ── 6. _compute_effective_confidence ──
    sep("6. _compute_effective_confidence")
    ec1 = _compute_effective_confidence(0.9, {"agrees": True, "confidence": 0.8})
    check(ec1 == 0.8, f"agree min={ec1}")

    ec2 = _compute_effective_confidence(0.9, {"agrees": False, "confidence": 0.8})
    check(ec2 == 0.0, f"disagree → 0")

    ec3 = _compute_effective_confidence(0.5, {"agrees": True, "confidence": 0.9})
    check(ec3 == 0.5, f"grade lower={ec3}")

    ec4 = _compute_effective_confidence(
        0.9, {"agrees": True, "confidence": 0.9, "from_fallback": True}
    )
    check(ec4 == 0.0, f"verify fallback → 0={ec4}")

    ec5 = _compute_effective_confidence(
        0.9, {"agrees": True, "confidence": 0.9}, grade_fallback=True
    )
    check(ec5 == 0.0, f"grade fallback → 0={ec5}")

    # ── 7. GradeResult default fields ──
    sep("7. GradeResult default status/confidence")
    r = GradeResult(is_correct=False, feedback="test")
    check(r.status == "applied", f"default status={r.status}")
    check(r.confidence == 0.0, f"default confidence={r.confidence}")

    # ── 8. text fallback → pending ──
    sep("8. text fallback forces pending")
    with patch("grade.call_llm", return_value="正确与否：正确\n评语：好"), \
         patch("grade._get_bkt_log") as mock_bkt, \
         patch("learner.kp_registry.normalize_kp_for_grade", return_value="极限"):
        fake_bkt = MagicMock()
        fake_bkt.get_kp_mastery.return_value = None
        mock_bkt.return_value = fake_bkt
        with tempfile.TemporaryDirectory() as td:
            with patch.object(config_mod, "DATA_DIR", td):
                r = grade_answer(mcq, "A", kp_name="极限", subject="math")
        check(r.status == "pending", f"fallback status={r.status}")
        check(not fake_bkt.record.called, "fallback no BKT.record")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL GRADE WRITE GATE TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
