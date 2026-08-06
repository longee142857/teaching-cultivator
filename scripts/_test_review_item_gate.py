# -*- coding: utf-8 -*-
"""BIG-TEACH-012a #7b: Review item LLM 闸测试（mock LLM）。"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import orchestrate as orch
from orchestrate import _review_item, orchestrate_push


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

    mcq_draft = "设函数连续，则\nA. 可导\nB. 有界\nC. 可积\nD. 单调"
    mcq_answer = "正确选项：B\n解析：闭区间连续必有界（示意）"

    # ── 1. _review_item accept ──
    sep("1. _review_item accept with JSON response")
    with patch("decide.router.call_llm") as mock_llm:
        mock_llm.return_value = '{"decision": "accept", "issues": [], "suggestion": ""}'
        result = _review_item(mcq_draft, mcq_answer, kp="函数极限与连续", difficulty="basic")
        check(result["decision"] == "accept", f"decision={result['decision']}")
        check(mock_llm.call_count == 1, "LLM called once")

    # ── 2. _review_item reject ──
    sep("2. _review_item reject")
    with patch("decide.router.call_llm") as mock_llm:
        mock_llm.return_value = (
            '{"decision": "reject", "issues": ["题干有歧义"], "suggestion": "请明确条件"}'
        )
        result = _review_item("某题", "A", kp="极限")
        check(result["decision"] == "reject", f"decision={result['decision']}")
        check(len(result.get("issues", [])) > 0, f"has issues: {result.get('issues')}")

    # ── 3. Non-JSON fallback → reject (fail-closed) ──
    sep("3. Non-JSON fallback → reject")
    with patch("decide.router.call_llm") as mock_llm:
        mock_llm.return_value = "Looks good to me"
        result = _review_item("Q", "A", kp="极限")
        check(result["decision"] == "reject", f"fallback reject={result['decision']}")
        check("review_item_parse_failed" in result.get("issues", []), "parse_failed issue")

    # ── 4. orchestrate_push with review accept ──
    sep("4. orchestrate_push with review accept")
    original_review = orch._review_item
    orch._review_item = lambda *a, **kw: {"decision": "accept", "issues": [], "suggestion": ""}

    def fake_polish(draft_body, answer_body, **kwargs):
        return draft_body

    orch._polish_or_orchestrate = fake_polish
    r = orchestrate_push(
        {"draft": mcq_draft, "answer": mcq_answer, "kp": "函数极限与连续"},
        subject="math",
        max_author_retries=0,
    )
    check(r["status"] == "accept", f"orchestrate accept={r['status']}")

    # ── 5. orchestrate_push with review reject → reject ──
    sep("5. orchestrate_push review reject → reject")
    orch._review_item = lambda *a, **kw: {"decision": "reject", "issues": ["模拟退回"], "suggestion": "fix"}
    orch._polish_or_orchestrate = fake_polish
    r2 = orchestrate_push(
        {"draft": mcq_draft, "answer": mcq_answer, "kp": "极限"},
        subject="math",
        max_author_retries=0,
    )
    check(r2["status"] == "reject", f"review reject status={r2['status']}")
    check("review_item" in r2.get("reason", ""), f"reason has review_item: {r2.get('reason')[:60]}")

    # ── 6. Reject then reauthor → accept ──
    sep("6. Review reject → reauthor → accept")
    call_count = [0]

    def rejecting_review(*a, **kw):
        call_count[0] += 1
        if call_count[0] <= 1:
            return {"decision": "reject", "issues": ["首次退回"], "suggestion": "fix"}
        return {"decision": "accept", "issues": [], "suggestion": ""}

    orch._review_item = rejecting_review

    def reauthor_fn():
        return {"draft": mcq_draft + "\n（修订版）", "answer": mcq_answer, "kp": "极限"}

    orch._polish_or_orchestrate = fake_polish
    r3 = orchestrate_push(
        {"draft": mcq_draft, "answer": mcq_answer, "kp": "极限"},
        subject="math",
        max_author_retries=1,
        reauthor_fn=reauthor_fn,
    )
    check(r3["status"] == "accept", f"reauthor then accept={r3['status']}")

    # Restore
    orch._review_item = original_review

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL REVIEW ITEM GATE TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
