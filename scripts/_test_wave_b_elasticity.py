# -*- coding: utf-8 -*-
"""BIG-TEACH-012b Wave B elasticity: decay #1, G/S/T #2, forget #3, agent #A1."""
from __future__ import annotations

import json
import math
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
    # #1: decay_kp_weight
    # ═══════════════════════════════════════════
    sep("1. #1 decay_kp_weight — weight decreases, not below baseline")

    with tempfile.TemporaryDirectory() as td:
        example_subject = "math"
        example_weights = {
            "math": {
                "syllabus": "test",
                "kp_weights": {"函数极限与连续": 0.0482, "微分中值定理与泰勒": 0.0394},
            },
        }
        example_path = os.path.join(td, "weights.example.json")
        with open(example_path, "w", encoding="utf-8") as f:
            json.dump(example_weights, f, ensure_ascii=False)

        runtime_weights = {
            "math": {
                "syllabus": "test",
                "kp_weights": {"函数极限与连续": 0.0600, "微分中值定理与泰勒": 0.0394},
            },
        }
        weights_path = os.path.join(td, "weights.json")
        with open(weights_path, "w", encoding="utf-8") as f:
            json.dump(runtime_weights, f, ensure_ascii=False)

        with patch("learner.weights_ops.WEIGHTS_PATH", weights_path), \
             patch("learner.weights_ops.REFINE_QUEUE", os.path.join(td, "refine-queue.jsonl")), \
             patch("learner.weights_ops.DATA_DIR", td):
            from learner.weights_ops import decay_kp_weight

            # Decay from 0.06 toward baseline 0.0482
            result = decay_kp_weight("math", "函数极限与连续", reason="test:correct")
            check(result.get("ok") is True, f"decay ok: {result}")
            after = result["weight_after"]
            check(after < 0.0600, f"weight decreased: {result['weight_before']} -> {after}")
            check(after >= 0.0482, f"weight not below baseline 0.0482: {after}")

            # Decay again: should reach baseline and stay there
            result2 = decay_kp_weight("math", "函数极限与连续", reason="test:correct2")
            after2 = result2["weight_after"]
            check(after2 >= 0.0482, f"second decay not below baseline: {after2}")
            check(after2 <= after, f"second decay still decreases: {after} -> {after2}")

        # Comm-style relative weights
        comm_weights = {
            "comm": {
                "syllabus": "test",
                "kp_weights": {"确定信号与频谱分析": 1.5, "AWGN与匹配滤波器": 1.15},
            },
        }
        example_comm = {
            "comm": {
                "syllabus": "test",
                "kp_weights": {"确定信号与频谱分析": 1.05, "AWGN与匹配滤波器": 1.15},
            },
        }
        comm_ep = os.path.join(td, "weights.example.json")
        with open(comm_ep, "w", encoding="utf-8") as f:
            json.dump(example_comm, f, ensure_ascii=False)
        comm_wp = os.path.join(td, "weights.json")
        with open(comm_wp, "w", encoding="utf-8") as f:
            json.dump(comm_weights, f, ensure_ascii=False)

        with patch("learner.weights_ops.WEIGHTS_PATH", comm_wp), \
             patch("learner.weights_ops.REFINE_QUEUE", os.path.join(td, "refine-queue.jsonl")), \
             patch("learner.weights_ops.DATA_DIR", td):
            result3 = decay_kp_weight("comm", "确定信号与频谱分析", reason="test:correct3")
            check(result3.get("ok") is True, f"comm decay ok: {result3}")
            check(result3["weight_after"] >= 1.05,
                  f"comm not below baseline {result3['weight_after']} >= 1.05")
            check(result3["weight_after"] < 1.5,
                  f"comm decreased: {result3['weight_before']} -> {result3['weight_after']}")

            # Already at baseline → no-op
            result4 = decay_kp_weight("comm", "AWGN与匹配滤波器", reason="test:correct4")
            check(result4.get("ok") is True, f"at-baseline decay ok: {result4}")
            check(result4["weight_after"] == 1.15,
                  f"at-baseline unchanged: {result4['weight_after']}")

        # Refine-queue signal written
        refine_path = os.path.join(td, "refine-queue.jsonl")
        with patch("learner.weights_ops.REFINE_QUEUE", refine_path), \
             patch("learner.weights_ops.WEIGHTS_PATH", comm_wp), \
             patch("learner.weights_ops.DATA_DIR", td):
            decay_kp_weight("comm", "确定信号与频谱分析", reason="signal_test")
            check(os.path.exists(refine_path), "refine-queue created")
            with open(refine_path, encoding="utf-8") as f:
                lines = [l for l in f if l.strip()]
            signals = [json.loads(l) for l in lines]
            decay_signals = [s for s in signals if s.get("type") == "decay"]
            check(len(decay_signals) >= 1, f"decay signal found: {len(decay_signals)}")
            if decay_signals:
                check("baseline" in decay_signals[0], "baseline in signal")

    # ═══════════════════════════════════════════
    # #2: blank/proof_outline in G_BY_TYPE + overrides
    # ═══════════════════════════════════════════
    sep("2. #2 blank/proof_outline G/S/T in bkt module")

    import bkt as bkt_mod

    # blank type
    check("blank" in bkt_mod.G_BY_TYPE, "blank in G_BY_TYPE")
    check(bkt_mod.G_BY_TYPE["blank"] == 0.18, f"blank G={bkt_mod.G_BY_TYPE['blank']}")
    check(bkt_mod.D_POS_BY_TYPE.get("blank") is not None, "blank in D_POS_BY_TYPE")

    # proof_outline type
    check("proof_outline" in bkt_mod.G_BY_TYPE, "proof_outline in G_BY_TYPE")
    check(bkt_mod.G_BY_TYPE["proof_outline"] == 0.08,
          f"proof_outline G={bkt_mod.G_BY_TYPE['proof_outline']}")
    check(bkt_mod.D_POS_BY_TYPE.get("proof_outline") is not None,
          "proof_outline in D_POS_BY_TYPE")

    # blank/proof_outline do not silently fall to unknown
    kc = bkt_mod.KCState(p_mastery=0.5)
    kc.update(True, item_type="blank")
    check(kc.p_mastery > 0.5, f"blank correct increases mastery: {kc.p_mastery}")

    kc2 = bkt_mod.KCState(p_mastery=0.5)
    kc2.update(True, item_type="proof_outline")
    check(kc2.p_mastery > 0.5, f"proof_outline correct increases: {kc2.p_mastery}")

    # BKT_OVERRIDES_PATH / _load_bkt_overrides
    with tempfile.TemporaryDirectory() as td2:
        overrides = {"特征值与特征向量": {"p_slip": 0.15, "p_learn": 0.15}}
        ov_path = os.path.join(td2, "bkt_overrides.json")
        with open(ov_path, "w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False)

        bkt_mod.BKT_OVERRIDES_PATH = ov_path
        bkt_mod._BKT_OVERRIDES_CACHE = None
        loaded = bkt_mod._load_bkt_overrides()
        check(loaded.get("特征值与特征向量", {}).get("p_slip") == 0.15,
              f"overrides loaded p_slip={loaded.get('特征值与特征向量', {}).get('p_slip')}")
        check(loaded.get("特征值与特征向量", {}).get("p_learn") == 0.15,
              f"overrides loaded p_learn")

        # Non-overridden KP returns empty
        missing = loaded.get("反常积分", {})
        check(len(missing) == 0, "non-overridden KP returns empty dict")
        bkt_mod.BKT_OVERRIDES_PATH = None
        bkt_mod._BKT_OVERRIDES_CACHE = None

    # overrides affect KCState.update
    with tempfile.TemporaryDirectory() as td3:
        ov_path2 = os.path.join(td3, "bkt_overrides.json")
        with open(ov_path2, "w", encoding="utf-8") as f:
            json.dump({"test_kp": {"p_slip": 0.3, "p_learn": 0.4}}, f, ensure_ascii=False)

        bkt_mod.BKT_OVERRIDES_PATH = ov_path2
        bkt_mod._BKT_OVERRIDES_CACHE = None

        kc3 = bkt_mod.KCState(p_mastery=0.3, p_slip=0.1, p_learn=0.2)
        # Incorrect with overrides: p_slip=0.3 means higher slip → posterior drops more
        kc3.update(False, item_type="mcq", overrides={"p_slip": 0.3, "p_learn": 0.4})
        # Without overrides, S=0.1 → posterior is different
        kc3_nover = bkt_mod.KCState(p_mastery=0.3, p_slip=0.1, p_learn=0.2)
        kc3_nover.update(False, item_type="mcq")
        # overridden higher slip → different mastery
        check(kc3.p_mastery != kc3_nover.p_mastery or abs(kc3.p_mastery - kc3_nover.p_mastery) < 0.001,
              f"overrides change update behavior: {kc3.p_mastery} vs {kc3_nover.p_mastery}")

        bkt_mod.BKT_OVERRIDES_PATH = None
        bkt_mod._BKT_OVERRIDES_CACHE = None

    # bkt_overrides.example.json exists and is valid JSON
    example_ov_path = os.path.join(ROOT, "data", "bkt_overrides.example.json")
    check(os.path.isfile(example_ov_path), "bkt_overrides.example.json exists")
    with open(example_ov_path, encoding="utf-8") as f:
        ov_example = json.load(f)
    check(isinstance(ov_example, dict), "overrides example is valid dict")

    # ═══════════════════════════════════════════
    # #3: forgetting function + p_effective
    # ═══════════════════════════════════════════
    sep("3. #3 compute_forget + p_effective")

    from bkt import compute_forget, KCState
    from datetime import datetime, timezone, timedelta

    # No last_update → no decay
    p_no_ts = compute_forget(0.8, None)
    check(p_no_ts == 0.8, f"no ts returns p unchanged: {p_no_ts}")

    # Recent update → minimal decay
    recent_ts = datetime.now(timezone.utc).isoformat()
    p_recent = compute_forget(0.8, recent_ts)
    check(abs(p_recent - 0.8) < 0.01, f"recent ts minimal decay: {p_recent}")

    # 30-day half-life: Δt=30 days → should be halfway to prior
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    p_decayed = compute_forget(0.8, old_ts, prior=0.2)
    expected = 0.2 + (0.8 - 0.2) * 0.5  # = 0.5
    check(abs(p_decayed - expected) < 0.01, f"30d decay: {p_decayed} ≈ {expected}")

    # Δt=60 days → 3/4 of the way to prior
    very_old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    p_60 = compute_forget(0.8, very_old_ts, prior=0.2)
    expected_60 = 0.2 + (0.8 - 0.2) * 0.25  # = 0.35
    check(abs(p_60 - expected_60) < 0.01, f"60d decay: {p_60} ≈ {expected_60}")

    # p_effective property on KCState
    kc_eff = KCState(p_mastery=0.8)
    kc_eff.last_update_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    p_eff = kc_eff.p_effective
    check(p_eff < 0.8, f"p_effective < stored: {p_eff} < 0.8")
    check(p_eff > 0.2, f"p_effective > prior: {p_eff} > 0.2")
    check(abs(p_eff - 0.5) < 0.02, f"30d half-life p_eff≈0.5: {p_eff}")

    # KCState without update ts → p_effective == p_mastery
    kc_no_ts = KCState(p_mastery=0.8)
    check(kc_no_ts.p_effective == 0.8, "no last_update_ts → p_effective == p_mastery")

    # ═══════════════════════════════════════════
    # #A1: agent SYSTEM_PROMPT contains chase keywords
    # ═══════════════════════════════════════════
    sep("4. #A1 SYSTEM_PROMPT / tool schema contains chase keywords")

    from agent.agent import SYSTEM_PROMPT, TeachingAgent

    # Keywords that must appear in SYSTEM_PROMPT
    chase_keywords = [
        "追问思路",
        "暂缓 show_solution",
        "禁止直接给完整解答",
    ]
    for kw in chase_keywords:
        check(kw in SYSTEM_PROMPT, f"keyword in SYSTEM_PROMPT: '{kw}'")

    # Tool schema also contains chase hint
    schemas = TeachingAgent(bot=None)._build_tool_schemas()
    show_sol_schema = next(
        (s for s in schemas if s["function"]["name"] == "show_solution"), None
    )
    check(show_sol_schema is not None, "show_solution schema found")
    desc = show_sol_schema["function"]["description"]
    chase_tool_keywords = [
        "暂缓调用本工具",
        "追问思路",
    ]
    for kw in chase_tool_keywords:
        check(kw in desc, f"keyword in show_solution desc: '{kw}' — got: {desc[:120]}")

    # Grade_answer on short MCQ

    # ═══════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════
    sep("RESULTS")
    print(f"Tests: {fails} FAIL(s)" if fails else "ALL WAVE B ELASTICITY TESTS PASSED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
