# -*- coding: utf-8 -*-
"""BIG-TEACH-012c Wave C reliability: #8 retry, #8b dedup, #9 transfer,
#10 RAG_FALLBACK, #11 style, #12 posix, #13 grade, #14 user_id."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


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

    # ═══════════════════════════════════════════
    # #8: Push retry queue
    # ═══════════════════════════════════════════
    sep("1. #8 Push retry queue — enqueue, process, dead letter")
    from deliver.push_retry_queue import (
        enqueue_retry, process_retry_queue, _load_queue, _save_queue,
        MAX_RETRIES, RETRY_INTERVAL_MINUTES,
    )

    # Config checks
    check(MAX_RETRIES == 2, f"MAX_RETRIES={MAX_RETRIES}")
    check(len(RETRY_INTERVAL_MINUTES) == 2, "2 retry intervals")
    check(RETRY_INTERVAL_MINUTES[0] == 30, f"first interval={RETRY_INTERVAL_MINUTES[0]}")
    check(RETRY_INTERVAL_MINUTES[1] == 60, f"second interval={RETRY_INTERVAL_MINUTES[1]}")

    # Dedup: same subject not double-enqueued
    with tempfile.TemporaryDirectory() as td:
        with patch("deliver.push_retry_queue.DATA_DIR", td):
            enqueue_retry("math", content="content_1")
            enqueue_retry("math", content="content_2")
            q = _load_queue()
            check(len(q) == 1, f"dedup enqueue: 1 entry vs {len(q)}")
            check(q[0]["content"] == "content_1", "first enqueue kept")

    # Enqueue + process with mock bot
    with tempfile.TemporaryDirectory() as td:
        with patch("deliver.push_retry_queue.DATA_DIR", td), \
             patch("deliver.push_retry_queue.RETRY_INTERVAL_MINUTES", [0, 0]):  # immediate retry
            enqueue_retry("math", content="retry_content")
            q = _load_queue()
            check(len(q) == 1, "enqueued 1 entry")

            mock_bot = MagicMock()
            bridge = MagicMock()
            bridge.send.return_value = True
            mock_bot._make_push_bridge.return_value = bridge

            n = process_retry_queue(mock_bot)
            check(n == 1, f"processed {n} entries")

            # After success, queue should be empty
            remain = _load_queue()
            check(len(remain) == 0, "queue empty after successful retry")

    # Exhaustion → dead letter
    with tempfile.TemporaryDirectory() as td:
        with patch("deliver.push_retry_queue.DATA_DIR", td), \
             patch("deliver.push_retry_queue.RETRY_INTERVAL_MINUTES", [0, 0, 0]):
            entry = {
                "subject": "math",
                "attempt": 3,
                "max_attempts": 2,
                "content": "",
            }
            _save_queue([entry])
            mock_bot2 = MagicMock()
            n = process_retry_queue(mock_bot2)
            check(n == 0, "exhausted entry not processed")
            dead_path = os.path.join(td, "push-retry-dead.jsonl")
            check(os.path.isfile(dead_path), "dead letter file created")
            with open(dead_path, encoding="utf-8") as f:
                dead = json.loads(f.readline())
            check(dead["subject"] == "math", f"dead subject={dead['subject']}")
            check("exhausted" in dead.get("dead_reason", ""), f"dead reason={dead.get('dead_reason')}")

    # Make sure DATA_DIR has closing quote (checking syntax)
    print("OK #8")

    # ═══════════════════════════════════════════
    # #8b: DingTalk inbound dedup
    # ═══════════════════════════════════════════
    sep("2. #8b DingTalk inbound msgId dedup")
    # Test _InboundDedup directly
    from deliver.dingtalk_bot import _InboundDedup

    dedup = _InboundDedup(ttl=600, max_size=100)

    # First claim succeeds
    ok1 = dedup.claim("msg-001")
    check(ok1 is True, "first claim ok")

    # Duplicate claim fails
    ok2 = dedup.claim("msg-001")
    check(ok2 is False, "duplicate claim blocked")

    # Different msgId passes
    ok3 = dedup.claim("msg-002")
    check(ok3 is True, "different msgId passes")

    # Empty msgId always passes
    ok4 = dedup.claim("")
    check(ok4 is True, "empty msgId passes")
    ok5 = dedup.claim(None)  # type: ignore[arg-type]
    check(ok5 is True, "None msgId passes")

    # Fingerprint dedup
    fp1 = dedup.make_fingerprint("conv1", "hello")
    fp2 = dedup.make_fingerprint("conv1", "hello")
    check(fp1 == fp2, "same args → same fingerprint")

    fp3 = dedup.make_fingerprint("conv1", "world")
    check(fp1 != fp3, "different text → different fingerprint")

    # claim_by_fingerprint
    dedup2 = _InboundDedup(ttl=600, max_size=100)
    c1 = dedup2.claim_by_fingerprint("conv1", "hello")
    check(c1 is True, "first fingerprint claim ok")
    c2 = dedup2.claim_by_fingerprint("conv1", "hello")
    check(c2 is False, "duplicate fingerprint blocked")
    c3 = dedup2.claim_by_fingerprint("conv1", "world")
    check(c3 is True, "different fingerprint passes")

    # TTL expiration
    dedup3 = _InboundDedup(ttl=0.1, max_size=100)
    check(dedup3.claim("exp-msg"), "ttl claim 1 ok")
    check(not dedup3.claim("exp-msg"), "ttl claim 2 blocked")
    time.sleep(0.15)
    check(dedup3.claim("exp-msg"), "ttl expired, claim ok again")

    # Max size eviction
    dedup4 = _InboundDedup(ttl=600, max_size=10)
    for i in range(10):
        dedup4.claim(f"key-{i:03d}")
    check(len(dedup4._seen) == 10, "max_size reached")
    # next claim evicts half
    dedup4.claim("key-010")
    check(len(dedup4._seen) <= 6, f"evicted: {len(dedup4._seen)} <= 6")

    print("OK #8b")

    # ═══════════════════════════════════════════
    # #9: Transfer inheritance with constraints
    # ═══════════════════════════════════════════
    sep("3. #9 Transfer inheritance with constraints")
    from learner.ability_cycle import ability_to_item_form

    # No last_push → fallback to default
    with tempfile.TemporaryDirectory() as td:
        with patch("learner.ability_cycle.DATA_DIR", td):
            form = ability_to_item_form("transfer", last_form="blank", subject="math")
            check(form == "blank", f"no last_push → inherit last_form={form}")

    # Create a fresh last_push with valid data
    with tempfile.TemporaryDirectory() as td:
        last_push = {
            "subject": "math",
            "item_form": "proof_outline",
            "timestamp": "2099-01-01T00:00:00",
        }
        with open(os.path.join(td, "last_push.json"), "w", encoding="utf-8") as f:
            json.dump(last_push, f)
        with patch("learner.ability_cycle.DATA_DIR", td):
            form = ability_to_item_form("transfer", last_form="proof_outline", subject="math")
            check(form == "proof_outline",
                  f"valid last_push → inherit {form}")

    # Expired (age > 36h)
    with tempfile.TemporaryDirectory() as td:
        import datetime
        old_ts = (datetime.datetime.now() - datetime.timedelta(hours=48)).isoformat()
        expired = {"subject": "math", "item_form": "blank", "timestamp": old_ts}
        with open(os.path.join(td, "last_push.json"), "w", encoding="utf-8") as f:
            json.dump(expired, f)
        with patch("learner.ability_cycle.DATA_DIR", td):
            from learner.ability_cycle import ITEM_FORM_MAP
            form = ability_to_item_form("transfer", last_form="blank", subject="math")
            # expired → not inherit blank, fallback to transfer default
            check(form != "blank", f"expired → fallback form={form}")
            check(form == ITEM_FORM_MAP.get("transfer", "mcq"),
                  f"expired → ITEM_FORM_MAP fallback {form}")

    # Cross-subject
    with tempfile.TemporaryDirectory() as td:
        cross = {"subject": "comm", "item_form": "blank", "timestamp": "2099-01-01T00:00:00"}
        with open(os.path.join(td, "last_push.json"), "w", encoding="utf-8") as f:
            json.dump(cross, f)
        with patch("learner.ability_cycle.DATA_DIR", td):
            # subject=math but last_push is comm → different subject, fallback
            form = ability_to_item_form("transfer", last_form="blank", subject="math")
            from learner.ability_cycle import ITEM_FORM_MAP
            check(form == ITEM_FORM_MAP.get("transfer", "mcq"),
                  f"cross-subject → fallback form={form}")

    # Invalid item_form
    with tempfile.TemporaryDirectory() as td:
        invalid = {"subject": "math", "item_form": "essay", "timestamp": "2099-01-01T00:00:00"}
        with open(os.path.join(td, "last_push.json"), "w", encoding="utf-8") as f:
            json.dump(invalid, f)
        with patch("learner.ability_cycle.DATA_DIR", td):
            form = ability_to_item_form("transfer", last_form="essay", subject="math")
            check(form != "essay", f"invalid form → fallback form={form}")

    print("OK #9")

    # ═══════════════════════════════════════════
    # #10: RAG_FALLBACK=abort
    # ═══════════════════════════════════════════
    sep("4. #10 RAG_FALLBACK=abort — strict enabled by default")
    from learner.rag_retrieve import rag_strict_enabled

    # Default: RAG_FALLBACK=abort → strict
    with patch("learner.rag_retrieve.RAG_FALLBACK", "abort"):
        check(rag_strict_enabled() is True, "RAG_FALLBACK=abort → strict")

    # RAG_FALLBACK=prompt → not strict (if RAG_STRICT also 0)
    with patch("learner.rag_retrieve.RAG_FALLBACK", "prompt"), \
         patch("learner.rag_retrieve._strict_default", return_value=False):
        check(rag_strict_enabled() is False, "RAG_FALLBACK=prompt + no strict → not strict")

    # RAG_STRICT still works
    with patch("learner.rag_retrieve.RAG_FALLBACK", "prompt"), \
         patch("learner.rag_retrieve._strict_default", return_value=True):
        check(rag_strict_enabled() is True, "RAG_STRICT=1 overrides")

    # RAG miss → abort (no author / no push content)
    from cultivate import generate as cultivate_generate
    from intervention import InterventionDecision

    with patch("learner.rag_retrieve.rag_strict_enabled", return_value=True), \
         patch("learner.rag_retrieve.rag_retrieve") as mock_rag:
        mock_rag.return_value = MagicMock(ok=False, hit_count=0, to_prompt_items=lambda: [])
        # Also mock needed deps so generate doesn't actually call LLM
        with patch("cultivate.RefPicker") as mock_picker, \
             patch("cultivate.call_llm") as mock_llm, \
             patch("cultivate.PromptBuilder") as mock_builder:
            mock_picker.return_value.pick.return_value = None
            builder_instance = MagicMock()
            builder_instance.build.return_value = ("system", "user")
            builder_instance.build_polish.return_value = ("sys", "usr")
            mock_builder.return_value = builder_instance
            mock_llm.return_value = ""

            decision = InterventionDecision("push", "intermediate",
                                           "函数极限与连续 [l3=math_01_01] [ability=recognize]", 3)
            result = cultivate_generate("math", decision, mastery=0.5, opportunity_count=3,
                                         consecutive_failures=1, source="schedule")
            check(result == "", f"RAG miss + abort → empty content, got={result!r}")

    print("OK #10")

    # ═══════════════════════════════════════════
    # #11: Per-subject style dynamics
    # ═══════════════════════════════════════════
    sep("5. #11 Per-subject style dynamics")
    from cultivate import _dynamic_style_pcts

    # Math baseline
    exam, theory = _dynamic_style_pcts(0, "math")
    check(exam == 70, f"math 0 fail exam_pct={exam} (expect 70)")
    check(theory == 30, f"math 0 fail theory_pct={theory}")

    # Math per_fail=8
    exam2, theory2 = _dynamic_style_pcts(1, "math")
    check(exam2 == 78, f"math 1 fail exam_pct={exam2} (expect 78)")

    # Math floor
    exam3, _ = _dynamic_style_pcts(0, "math")
    # Already 70 > floor 60, so floor not hit

    # Math ceil
    exam4, _ = _dynamic_style_pcts(3, "math")
    check(exam4 == 90, f"math 3 fails exam_pct={exam4} (expect ceil 90)")

    # Comm baseline
    exam5, theory5 = _dynamic_style_pcts(0, "comm")
    check(exam5 == 55, f"comm 0 fail exam_pct={exam5} (expect 55)")
    check(theory5 == 45, f"comm 0 fail theory_pct={theory5}")

    # Comm per_fail=5
    exam6, _ = _dynamic_style_pcts(1, "comm")
    check(exam6 == 60, f"comm 1 fail exam_pct={exam6} (expect 60)")

    # Comm ceiling at 85
    exam7, _ = _dynamic_style_pcts(6, "comm")
    check(exam7 == 85, f"comm 6 fails exam_pct={exam7} (expect ceil 85)")

    # Unknown subject → uses fallback
    exam8, _ = _dynamic_style_pcts(0, "review")
    check(exam8 >= 60, f"review 0 fail exam_pct={exam8} (fallback >= 60)")

    print("OK #11")

    # ═══════════════════════════════════════════
    # #12: Linux agent proxy sidecar
    # ═══════════════════════════════════════════
    sep("6. #12 Linux agent proxy sidecar")
    from deliver.github_pusher import _ensure_proxy_sidecar

    # Mock posix platform + missing .sh → non-silent warning
    with patch("sys.platform", "linux"), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.print") as mock_print:
        result = _ensure_proxy_sidecar()
        check(result is False, "missing .sh returns False")
        printed = "".join(a[0] for a, _ in mock_print.call_args_list if a)
        check("WARNING" in printed.upper(), f"non-silent warning: {printed[:100]}")

    # Mock windows + missing .bat → non-silent warning
    with patch("sys.platform", "win32"), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.print") as mock_print:
        result = _ensure_proxy_sidecar()
        check(result is False, "missing .bat returns False")
        printed = "".join(a[0] for a, _ in mock_print.call_args_list if a)
        check("WARNING" in printed.upper(), f"non-silent warning: {printed[:100]}")

    print("OK #12")

    # ═══════════════════════════════════════════
    # #13: Biweekly structured grade parsing
    # ═══════════════════════════════════════════
    sep("7. #13 Biweekly structured grade parsing")
    from grade import _parse_grade_json
    from learner.biweekly_exam import submit_answer_md

    # _parse_grade_json works on structured LLM output
    valid = _parse_grade_json('{"verdict": "correct", "confidence": 0.9, "explanation": "ok"}')
    check(valid is not None and valid["verdict"] == "correct", "parse valid JSON")

    # "不正确" must not be parsed as correct
    partial_json = _parse_grade_json('{"verdict": "incorrect", "confidence": 0.95}')
    check(partial_json is not None and partial_json["verdict"] == "incorrect",
          "incorrect verdict parsed corrected")

    # Text fallback should not misjudge 不正确
    from grade import _parse_grade_verdict
    is_correct, credit = _parse_grade_verdict("正确与否：不正确\n评语：完全错误")
    check(is_correct is False, "text '不正确' → not correct")

    # "正确" in verdict line → is correct
    is_correct2, credit2 = _parse_grade_verdict("正确与否：正确\n评语：做得好")
    check(is_correct2 is True, "text '正确' → correct")

    # "部分正确" → not correct, credit=0.5
    is_correct3, credit3 = _parse_grade_verdict("正确与否：部分正确\n评语：半对")
    check(is_correct3 is False and credit3 == 0.5, "partial correct")

    # submit_answer_md with empty input
    result_empty = submit_answer_md("")
    check("空" in result_empty, f"empty md result: {result_empty[:60]}")

    print("OK #13")

    # ═══════════════════════════════════════════
    # #14: LEARNER_USER_ID
    # ═══════════════════════════════════════════
    sep("8. #14 LEARNER_USER_ID config and usage")

    # Default value
    from config import LEARNER_USER_ID
    check(LEARNER_USER_ID == "wx_123", f"default LEARNER_USER_ID={LEARNER_USER_ID}")

    # Env override
    with patch.dict(os.environ, {"LEARNER_USER_ID": "test_user_456"}, clear=False):
        # Re-import to pick up env
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        check(config_mod.LEARNER_USER_ID == "test_user_456",
              f"env override: {config_mod.LEARNER_USER_ID}")

    # snapshot.USER_ID uses config
    from learner.snapshot import USER_ID
    check(USER_ID is not None and len(USER_ID) > 0, f"snapshot USER_ID={USER_ID}")

    # .env.example has the field
    env_example = os.path.join(ROOT, ".env.example")
    check(os.path.isfile(env_example), ".env.example exists")
    with open(env_example, encoding="utf-8") as f:
        content = f.read()
    check("LEARNER_USER_ID" in content, "LEARNER_USER_ID documented in .env.example")

    print("OK #14")

    # ═══════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════
    sep("RESULTS")
    if fails:
        print(f"WAVE C: {fails} FAIL(s)")
        sys.exit(1)
    print("ALL WAVE C RELIABILITY TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
