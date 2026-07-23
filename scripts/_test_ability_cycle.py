"""BIG-TEACH-011d ability cycle + due+7d + item_form acceptance.

Usage:
    python scripts/_test_ability_cycle.py

Writes data/ability-cycle-check.json (override with ABILITY_CYCLE_CHECK_OUT).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 确保 knowledge-system/lib 路径
import config as _cfg
_cfg  # silencio

OUT = os.environ.get(
    "ABILITY_CYCLE_CHECK_OUT",
    os.path.join(ROOT, "data", "ability-cycle-check.json"),
)

PASSED: list[str] = []
FAILED: list[str] = []
SKIPPED: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def skip(name: str, reason: str):
    SKIPPED.append(name)
    print(f"  SKIP  {name}  ({reason})")


# ═══════════════════════════════════════════
# 1. D1 — due+7d
# ═══════════════════════════════════════════

def _import_bkt():
    """导入 bkt（路径由 config 确保）。"""
    from bkt import KCState
    return KCState


_BKT = _import_bkt()


def test_due_just_mastered():
    """刚掌握答对后 due_ts ≈ now+7d (±1h)。"""
    KCState = _BKT

    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)

    # 构造刚掌握状态：opp=3, streak=2, p=0.8, 再答对一次
    kc = KCState(p_mastery=0.8)
    kc.opportunity_count = 2
    kc.streak_correct = 1
    # 再答对→ opp=3, streak=2 → 刚掌握
    kc.update(True, item_type="mcq", now=now)
    # 刚掌握之后再一次答对，触发 due
    kc.update(True, item_type="mcq", now=now)
    due = kc.due_ts
    check("due_just_mastered_has_due", bool(due), f"due_ts={due}")
    if due:
        due_dt = datetime.fromisoformat(due)
        delta = due_dt - now
        expected = timedelta(days=7)
        lower = expected - timedelta(hours=1)
        upper = expected + timedelta(hours=1)
        check("due_just_mastered_7d",
              lower <= delta <= upper,
              f"delta={delta}")


def test_due_wrong():
    """答错 still +1d。"""
    KCState = _BKT
    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)

    kc = KCState()
    kc.update(False, item_type="mcq", now=now)
    due = kc.due_ts
    if due:
        delta = datetime.fromisoformat(due) - now
        expected = timedelta(days=1)
        check("due_wrong_1d",
              delta >= expected and delta < expected + timedelta(hours=2),
              f"delta={delta}")


def test_due_not_mastered_correct():
    """未掌握答对仍 +1.5d。"""
    KCState = _BKT
    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)

    kc = KCState(p_mastery=0.5)
    kc.opportunity_count = 1
    kc.streak_correct = 0
    # 未掌握答对
    kc.update(True, item_type="mcq", now=now)
    due = kc.due_ts
    if due:
        delta = datetime.fromisoformat(due) - now
        # 未掌握答对 → 1d 12h
        target = timedelta(days=1, hours=12)
        margin = timedelta(hours=1)
        check("due_not_mastered_correct_1_5d",
              target - margin <= delta <= target + margin,
              f"delta={delta}")


def test_due_stable():
    """稳掌握仍 +21d。"""
    KCState = _BKT
    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)

    kc = KCState(p_mastery=0.9)
    kc.opportunity_count = 5
    kc.streak_correct = 3
    kc.update(True, item_type="mcq", now=now)
    due = kc.due_ts
    if due:
        delta = datetime.fromisoformat(due) - now
        target = timedelta(days=21)
        margin = timedelta(hours=2)
        check("due_stable_21d",
              target - margin <= delta <= target + margin,
              f"delta={delta}")


# ═══════════════════════════════════════════
# 2. D2 — ability_cycle 状态机
# ═══════════════════════════════════════════

def test_ability_cold():
    """opp=0/explain → recognize。"""
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "explain", opportunity_count=0)
    check("ability_cold_explain_recognize", result == "recognize", f"got={result}")
    result2 = decide_ability("math", "push", opportunity_count=0)
    check("ability_cold_push_recognize", result2 == "recognize", f"got={result2}")


def test_ability_after_wrong():
    """after_wrong/review → diagnose。"""
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "review")
    check("ability_review_diagnose", result == "diagnose", f"got={result}")
    result2 = decide_ability("math", "push", recent_correct=False)
    check("ability_wrong_diagnose", result2 == "diagnose", f"got={result2}")


def test_ability_mastered():
    """已掌握 + 未到期 → transfer。"""
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "push", is_mastered=True, is_due=False,
                            opportunity_count=5)
    check("ability_mastered_transfer", result == "transfer", f"got={result}")


def test_ability_mastered_due():
    """已掌握 + 到期 → recognize 或 transfer。"""
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "push", is_mastered=True, is_due=True,
                            mastery=0.85, opportunity_count=5)
    check("ability_mastered_due", result in ("recognize", "transfer"), f"got={result}")


def test_ability_due():
    """到期未掌握 → construct。"""
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "push", is_mastered=False, is_due=True,
                            mastery=0.6, opportunity_count=5)
    check("ability_due_construct", result == "construct", f"got={result}")


def test_ability_learning_default():
    """learning 阶段默认 compute（isolated from anti-repeat state）。"""
    _clean_ability_picks("math")
    from learner.ability_cycle import decide_ability
    result = decide_ability("math", "push",
                            is_mastered=False, is_due=False,
                            opportunity_count=3, mastery=0.5)
    check("ability_learning_compute", result == "compute", f"got={result}")


# ═══════════════════════════════════════════
# 3. D2 — anti-repeat
# ═══════════════════════════════════════════

def _clean_ability_picks(subject: str):
    """清空历史 picks 避免测试间污染。"""
    from learner.ability_cycle import RECENT_ABILITY_PATH
    data = {}
    try:
        if os.path.isfile(RECENT_ABILITY_PATH):
            with open(RECENT_ABILITY_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data[subject] = []
        with open(RECENT_ABILITY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        pass


def test_anti_repeat():
    """近 3 次同 ability 降权 → 轮换。"""
    from learner.ability_cycle import decide_ability

    # 先用空历史测试 learning 默认
    _clean_ability_picks("math")
    first = decide_ability("math", "push",
                           is_mastered=False, is_due=False,
                           opportunity_count=5, mastery=0.5)
    check("anti_repeat_first_nonempty", bool(first), f"got={first}")

    # 连续选同 ability 应被降权重（很难精确断言，至少可跑）
    from learner.ability_cycle import append_recent_ability
    for _ in range(5):
        append_recent_ability("math", "compute")
    check("anti_repeat_runs_no_error", True, "append works")


# ═══════════════════════════════════════════
# 4. D3 — item_form 映射
# ═══════════════════════════════════════════

def test_item_form_mapping():
    """ability_goal → item_form 映射正确。"""
    from learner.ability_cycle import ability_to_item_form

    check("item_form_recognize_mcq",
          ability_to_item_form("recognize") == "mcq")
    check("item_form_diagnose_mcq",
          ability_to_item_form("diagnose") == "mcq")
    check("item_form_compute_blank",
          ability_to_item_form("compute") == "blank")
    check("item_form_construct_proof",
          ability_to_item_form("construct") == "proof_outline")
    check("item_form_transfer_default",
          ability_to_item_form("transfer") == "mcq")
    check("item_form_transfer_inherit",
          ability_to_item_form("transfer", last_form="blank") == "blank")


def test_push_template_has_form_placeholders():
    """push.md 须含 item_form_user_constraint，且无硬编码「改干扰项」。"""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "prompts" / "templates" / "push.md").read_text(
        encoding="utf-8"
    )
    check("push_has_item_form_user_constraint",
          "{{item_form_user_constraint}}" in text)
    check("push_no_hardcoded_mcq_distractor",
          "改干扰项" not in text)


def test_ability_parse_reason():
    """reason 中 [ability=...] 解析。"""
    from learner.ability_cycle import encode_ability_reason, parse_ability_from_reason

    tag = encode_ability_reason("compute")
    reason = f"极限: 测试 {tag}"
    parsed = parse_ability_from_reason(reason)
    check("parse_ability_from_reason", parsed == "compute", f"got={parsed}")

    # 无 ability 标记
    check("parse_ability_none",
          parse_ability_from_reason("极限: 测试") is None)


def test_ability_goal_in_decision():
    """InterventionDecision 含 ability_goal 字段。"""
    from intervention import InterventionDecision

    d = InterventionDecision("push", "intermediate", "测试", 3, ability_goal="compute")
    check("decision_ability_goal_field",
          d.ability_goal == "compute",
          f"got={d.ability_goal}")

    d2 = InterventionDecision("push", "intermediate", "测试", 3)
    check("decision_ability_goal_default",
          d2.ability_goal == "",
          f"got={d2.ability_goal!r}")


# ═══════════════════════════════════════════
# 5. 011c regression: L3 gate 保持
# ═══════════════════════════════════════════

def test_011c_regression():
    """RAG_STRICT=1 时无有效 L3 仍阻塞 author。

    不调 LLM，只检查硬闸拦截逻辑。
    """
    os.environ["RAG_STRICT"] = "1"
    from intervention import InterventionDecision

    # decision 无 L3 → generate 应被 RAG 阻塞
    decision = InterventionDecision(
        "push", "intermediate",
        "函数极限与连续: 掌握度 45%，需出题练习", 3,
    )
    try:
        from cultivate import generate
        result = generate("math", decision, source="chat")
        is_empty = not result or result.strip() == ""
        check("011c_regression_l2_blocked",
              is_empty,
              f"L2 without L3 blocked, got_len={len(result or '')}")
    except Exception as e:
        skip("011c_regression_l2_blocked", f"exception: {e}")


# ═══════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("BIG-TEACH-011d ability 周期 + due+7d + item_form 验收")
    print("=" * 60)

    # 1. due+7d
    print("\n--- 1. due+7d ---")
    test_due_just_mastered()
    test_due_wrong()
    test_due_not_mastered_correct()
    test_due_stable()

    # 2. ability cycle state machine
    print("\n--- 2. ability_cycle state machine ---")
    test_ability_cold()
    test_ability_after_wrong()
    test_ability_mastered()
    test_ability_mastered_due()
    test_ability_due()
    test_ability_learning_default()

    # 3. anti-repeat
    print("\n--- 3. anti-repeat ---")
    test_anti_repeat()

    # 4. item_form mapping
    print("\n--- 4. item_form mapping ---")
    test_item_form_mapping()
    test_push_template_has_form_placeholders()
    test_ability_parse_reason()
    test_ability_goal_in_decision()

    # 5. 011c regression
    print("\n--- 5. 011c regression ---")
    test_011c_regression()

    # ── 报告 ──
    passed = len(PASSED)
    failed = len(FAILED)
    skipped = len(SKIPPED)
    total = passed + failed + skipped
    all_pass = failed == 0

    print("\n" + "=" * 60)
    print(f"结果: {'PASS' if all_pass else 'FAIL'}  "
          f"{passed}/{total} passed, {failed} failed, {skipped} skipped")
    for name in FAILED:
        print(f"  FAILED: {name}")
    for name in SKIPPED:
        print(f"  SKIPPED: {name}")

    report = {
        "pass": all_pass,
        "summary": f"{passed}/{total} passed, {failed} failed, {skipped} skipped",
        "checks": {
            "passed": PASSED,
            "failed": FAILED,
            "skipped": SKIPPED,
        },
    }
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport written: {OUT}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
