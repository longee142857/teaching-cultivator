"""Phase C 质量闸 / 编排回归（不调真 LLM）。"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quality_gate import (  # noqa: E402
    check_draft_answer,
    extract_answer_letter,
    extract_mc_options,
    looks_contaminated,
)
from orchestrate import orchestrate_push  # noqa: E402

OUT = os.path.join(
    os.environ.get("PHASE_C_OUT", os.path.join(ROOT, "data")),
    "phase-c-check.json",
)


def test_pollution_reject():
    draft = "求极限\nA. 1\nB. 2\nC. 3\nD. 4"
    answer = "正确选项：A\n重新出题：我们调整一下选项"
    issues = check_draft_answer(draft, answer)
    assert any("contaminate" in i for i in issues), issues
    assert looks_contaminated(answer)
    r = orchestrate_push(
        {"draft": draft, "answer": answer, "kp": "极限"},
        subject="math",
        max_author_retries=0,
    )
    assert r["status"] == "reject", r
    print("OK pollution reject")


def test_duplicate_options():
    draft = "题\nA. 相同\nB. 相同\nC. 别的\nD. 再别的"
    answer = "正确选项：A\n解析：略"
    issues = check_draft_answer(draft, answer)
    assert any("duplicate_option" in i for i in issues), issues
    print("OK duplicate options")


def test_answer_not_in_options():
    draft = "题\nA. 1\nB. 2\nC. 3\nD. 4"
    answer = "正确选项：E\n解析：无"
    issues = check_draft_answer(draft, answer)
    assert any("answer_letter_not_in_options" in i for i in issues), issues
    print("OK answer letter")


def test_leak_in_draft():
    draft = "题\nA. 1\nB. 2\nC. 3\nD. 4\n正确选项：B"
    answer = "正确选项：B\n解析：ok"
    issues = check_draft_answer(draft, answer)
    assert "answer_leak_in_draft" in issues, issues
    print("OK leak in draft")


def test_set_aside_lead_stripped_on_push():
    """Polish 把「先放一放」写回题干开头时，push 发送稿要先剥掉再质检。"""
    draft = (
        "求 $\\lim_{x\\to 0}\\sin x/x$\n"
        "A. 0\n"
        "B. 1\n"
        "C. 2\n"
        "D. 不存在"
    )
    answer = "正确选项：B\n解析：标准极限，示意足够长"
    assert check_draft_answer(draft, answer) == []
    lead = "把这个题先放一放。\n\n" + draft

    import orchestrate as orch

    def fake_polish(draft_body, answer_body, **kwargs):
        return lead

    with patch.object(orch, "_polish_or_orchestrate", fake_polish), patch.object(
        orch,
        "_review_item",
        lambda *a, **kw: {"decision": "accept", "issues": [], "parse_ok": True},
    ):
        r = orch.orchestrate_push(
            {"draft": draft, "answer": answer, "kp": "极限", "decision_type": "push"},
            subject="math",
            source="schedule",
            max_author_retries=0,
        )
    assert r["status"] == "accept", r
    assert "放一放" not in (r.get("content") or ""), r
    assert "sin" in r["content"]
    print("OK push strips 先放一放 lead-in")


def test_set_aside_in_body_rejects():
    draft = (
        "求极限。先放一放再选。\n"
        "A. 0\n"
        "B. 1\n"
        "C. 2\n"
        "D. 不存在"
    )
    answer = "正确选项：B\n解析：标准极限示意"
    issues = check_draft_answer(draft, answer)
    assert any("放一放" in i for i in issues), issues
    r = orchestrate_push(
        {"draft": draft, "answer": answer, "kp": "极限", "decision_type": "push"},
        subject="math",
        source="schedule",
        max_author_retries=0,
    )
    assert r["status"] == "reject", r
    assert any("放一放" in i for i in r["issues"]), r
    print("OK in-body 放一放 rejects")


def test_clean_mcq_accept_without_llm(monkey=None):
    """质检通过后，mock 掉 LLM，应 accept fallback/polish path。"""
    draft = (
        "设函数连续，则\n"
        "A. 可导\n"
        "B. 有界\n"
        "C. 可积\n"
        "D. 单调"
    )
    answer = "正确选项：B\n解析：闭区间连续必有界（示意）"
    issues = check_draft_answer(draft, answer)
    assert issues == [], issues
    assert extract_answer_letter(answer) == "B"
    assert set(extract_mc_options(draft)) == {"A", "B", "C", "D"}

    import orchestrate as orch

    def fake_polish(draft_body, answer_body, **kwargs):
        return draft_body

    orch._polish_or_orchestrate = fake_polish  # type: ignore
    orch._review_item = lambda *a, **kw: {"decision": "accept", "issues": [], "suggestion": ""}
    r = orch.orchestrate_push(
        {"draft": draft, "answer": answer, "kp": "函数极限与连续"},
        subject="math",
        max_author_retries=0,
    )
    assert r["status"] == "accept", r
    assert "可导" in r["content"]
    print("OK clean accept (mocked orchestrate)")


def main() -> int:
    test_pollution_reject()
    test_duplicate_options()
    test_answer_not_in_options()
    test_leak_in_draft()
    test_set_aside_lead_stripped_on_push()
    test_set_aside_in_body_rejects()
    test_clean_mcq_accept_without_llm()
    report = {
        "PASS": True,
        "checks": [
            "pollution_reject",
            "duplicate_options",
            "answer_letter",
            "leak_in_draft",
            "set_aside_lead_stripped",
            "set_aside_in_body_rejects",
            "clean_accept_mocked",
        ],
    }
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("PASS all", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
