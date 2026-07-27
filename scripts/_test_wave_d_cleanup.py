# -*- coding: utf-8 -*-
"""BIG-TEACH-012d Wave D cleanup: #15 SSL, #16 LP退役, #17 refine-queue归档."""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
    # #15: SSL verify default on
    # ═══════════════════════════════════════════
    sep("1. #15 SSL verify — default on, env escape, constant assertion")

    # Default config
    from config import SSL_VERIFY
    check(SSL_VERIFY is True, f"default SSL_VERIFY={SSL_VERIFY} (expect True)")

    # SSL_VERIFY=0 disables
    with patch.dict(os.environ, {"SSL_VERIFY": "0"}, clear=False):
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        check(config_mod.SSL_VERIFY is False, "SSL_VERIFY=0 → False")

    # agent/agent.py imports SSL_VERIFY
    from agent.agent import TeachingAgent
    agent = TeachingAgent()
    # Check that _call_llm method exists and uses verify param
    import inspect
    src = inspect.getsource(agent._call_llm)
    check("verify=SSL_VERIFY" in src or "verify=" in src, "agent._call_llm uses verify")

    # decide/router.py uses verify param
    from decide.router import call_llm as router_call_llm
    src2 = inspect.getsource(router_call_llm)
    check("verify=SSL_VERIFY" in src2 or "verify=" in src2, "router.call_llm uses verify")

    print("OK #15")

    # ═══════════════════════════════════════════
    # #16: LP退役 — no crash, answer-log based
    # ═══════════════════════════════════════════
    sep("2. #16 LP退役 — analyze/build_weekly with no LP file")

    from learner.model import analyze, analyze_kp_trends, load_bkt_log

    # No LP file at all → analyze() should not crash
    with tempfile.TemporaryDirectory() as td:
        # Point DATA_DIR to empty temp dir (no LP, no answer-log)
        with patch("learner.model.DATA_DIR", td), \
             patch("learner.model.ANSWER_LOG", os.path.join(td, "answer-log.jsonl")), \
             patch("learner.profile.DATA_DIR", td):
            from learner.profile import build_weekly
            # build_weekly internally calls analyze()
            profile = build_weekly(weeks=1)
            check(profile is not None, "build_weekly returned a profile")
            check(profile.kp_trends == [], f"no logs → empty kp_trends, got={profile.kp_trends}")
            check(profile.error_patterns == [], f"no logs → empty error_patterns")

    # analyze() with empty answer-log
    with tempfile.TemporaryDirectory() as td:
        # Create empty answer-log
        log_path = os.path.join(td, "answer-log.jsonl")
        with open(log_path, "w") as f:
            f.write("")
        with patch("learner.model.DATA_DIR", td), \
             patch("learner.model.ANSWER_LOG", log_path):
            profile = analyze(weeks=1)
            check(profile is not None, "analyze with empty log returned profile")
            check(profile.engagement["total_pushes"] == 0, "empty log → 0 pushes")

    # analyze_kp_trends with real log data (LP-independent)
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "answer-log.jsonl")
        entries = [
            {"ts": "2026-07-20T10:00:00", "user_id": "wx_123",
             "knowledge_point": "极限与连续", "correct": True,
             "mastery_before": 0.3, "mastery_after": 0.5},
            {"ts": "2026-07-21T10:00:00", "user_id": "wx_123",
             "knowledge_point": "导数与微分", "correct": False,
             "mastery_before": 0.4, "mastery_after": 0.35},
            {"ts": "2026-07-22T10:00:00", "user_id": "wx_123",
             "knowledge_point": "极限与连续", "correct": True,
             "mastery_before": 0.5, "mastery_after": 0.7},
        ]
        with open(log_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with patch("learner.model.ANSWER_LOG", log_path):
            log = load_bkt_log()
            check(len(log) == 3, f"loaded 3 log entries, got={len(log)}")
            trends = analyze_kp_trends(log)
            check(len(trends) == 2, f"2 KPs with trends, got={len(trends)}")
            # Limits & continuity: first 0.3 → latest 0.7
            for t in trends:
                if t.name == "极限与连续":
                    check(t.mastery_before == 0.3, f"极 limits mastery_before={t.mastery_before}")
                    check(t.mastery_after == 0.7, f"极限 mastery_after={t.mastery_after}")
                    check(t.opportunity_count == 2, f"极限 count={t.opportunity_count}")

    # Dead import check: cultivate.py no longer imports LP_PATH
    import ast
    with open(os.path.join(ROOT, "cultivate.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    lp_imports = [n for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and any(
                      alias.name == "LP_PATH" for alias in n.names)]
    check(len(lp_imports) == 0, "cultivate.py no longer imports LP_PATH")

    # config.py still has LP_PATH (as deprecated)
    from config import LP_PATH
    check(LP_PATH is not None and LP_PATH.endswith("learning-progress.json"),
          f"config.LP_PATH still defined as {LP_PATH}")

    print("OK #16")

    # ═══════════════════════════════════════════
    # #17: Refine-queue archive
    # ═══════════════════════════════════════════
    sep("3. #17 Refine-queue archive — rotation by size and age")

    from learner.weights_ops import (
        archive_refine_queue,
        REFINE_QUEUE, REFINE_QUEUE_ARCHIVE_DIR,
        REFINE_QUEUE_MAX_ENTRIES, REFINE_QUEUE_MAX_AGE_DAYS,
    )

    # Constants check
    check(REFINE_QUEUE_MAX_ENTRIES == 500, f"max_entries={REFINE_QUEUE_MAX_ENTRIES}")
    check(REFINE_QUEUE_MAX_AGE_DAYS == 30, f"max_age_days={REFINE_QUEUE_MAX_AGE_DAYS}")

    # No file → no-op
    with tempfile.TemporaryDirectory() as td:
        with patch("learner.weights_ops.REFINE_QUEUE", os.path.join(td, "refine-queue.jsonl")), \
             patch("learner.weights_ops.REFINE_QUEUE_ARCHIVE_DIR", os.path.join(td, "archive")):
            result = archive_refine_queue(max_entries=10, max_age_days=30)
            check(result["ok"] is True, "no file → ok")
            check(result["archived"] == 0, "no file → 0 archived")

    # Few entries (< max) → no archive
    with tempfile.TemporaryDirectory() as td:
        qpath = os.path.join(td, "refine-queue.jsonl")
        with open(qpath, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(json.dumps({"ts": "2026-07-20T10:00:00", "kp": f"kp_{i}"}) + "\n")
        with patch("learner.weights_ops.REFINE_QUEUE", qpath), \
             patch("learner.weights_ops.REFINE_QUEUE_ARCHIVE_DIR", os.path.join(td, "archive")):
            result = archive_refine_queue(max_entries=10, max_age_days=30)
            check(result["ok"] is True, "under limit → ok")
            check(result["archived"] == 0, "under limit → 0 archived")
            check(result["remaining"] == 5, f"under limit → 5 remain, got={result['remaining']}")

    # Over max_entries → archive old, keep latest N
    with tempfile.TemporaryDirectory() as td:
        qpath = os.path.join(td, "refine-queue.jsonl")
        with open(qpath, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(json.dumps({"ts": "2026-07-20T10:00:00", "kp": f"kp_{i:03d}"}) + "\n")
        arc_dir = os.path.join(td, "archive")
        with patch("learner.weights_ops.REFINE_QUEUE", qpath), \
             patch("learner.weights_ops.REFINE_QUEUE_ARCHIVE_DIR", arc_dir):
            result = archive_refine_queue(max_entries=10, max_age_days=30)
            check(result["ok"] is True, "over limit → ok")
            check(result["archived"] == 5, f"archived 5 old, got={result['archived']}")
            check(result["remaining"] == 10, f"10 remain, got={result['remaining']}")

            # Verify active queue shortened
            with open(qpath, encoding="utf-8") as f:
                remaining = [l for l in f if l.strip()]
            check(len(remaining) == 10, f"active queue now 10, got={len(remaining)}")
            # Verify archived file exists
            import glob
            arc_files = glob.glob(os.path.join(arc_dir, "*.jsonl"))
            check(len(arc_files) >= 1, f"archive file(s) exist: {arc_files}")

    # Oldest entry > 30 days → archive
    with tempfile.TemporaryDirectory() as td:
        qpath = os.path.join(td, "refine-queue.jsonl")
        with open(qpath, "w", encoding="utf-8") as f:
            # 非常旧的条目
            f.write(json.dumps({"ts": "2025-01-01T10:00:00", "kp": "old_kp"}) + "\n")
            # 近期条目
            for i in range(4):
                f.write(json.dumps({"ts": "2026-07-20T10:00:00", "kp": f"kp_{i}"}) + "\n")
        arc_dir = os.path.join(td, "archive")
        with patch("learner.weights_ops.REFINE_QUEUE", qpath), \
             patch("learner.weights_ops.REFINE_QUEUE_ARCHIVE_DIR", arc_dir):
            result = archive_refine_queue(max_entries=10, max_age_days=7)
            check(result["ok"] is True, "old entry → ok")
            check(result["archived"] > 0, f"archived some, got={result['archived']}")

    # Verify archive_refine_queue called lazily after append
    with tempfile.TemporaryDirectory() as td:
        qpath = os.path.join(td, "refine-queue.jsonl")
        with open(qpath, "w", encoding="utf-8") as f:
            for i in range(12):
                f.write(json.dumps({"ts": "2026-07-20T10:00:00", "kp": f"kp_{i:03d}"}) + "\n")
        arc_dir = os.path.join(td, "archive")
        with patch("learner.weights_ops.REFINE_QUEUE", qpath), \
             patch("learner.weights_ops.REFINE_QUEUE_ARCHIVE_DIR", arc_dir), \
             patch("learner.weights_ops.REFINE_QUEUE_MAX_ENTRIES", 10), \
             patch("learner.weights_ops.REFINE_QUEUE_MAX_AGE_DAYS", 30):
            # _append_refine_signal will trigger archive after write
            from learner.weights_ops import _append_refine_signal
            with patch("learner.weights_ops.archive_refine_queue", wraps=archive_refine_queue) as mock_archive:
                _append_refine_signal("math", "极限", "test", 0.1, 0.12)
                check(mock_archive.called, "archive_refine_queue called after append")

    print("OK #17")

    # ═══════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════
    sep("RESULTS")
    if fails:
        print(f"WAVE D: {fails} FAIL(s)")
        sys.exit(1)
    print("ALL WAVE D CLEANUP TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
