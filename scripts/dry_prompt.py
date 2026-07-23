#!/usr/bin/env python3
"""打印组装后的 system+user 提示词，不调 LLM；用于验收。

Usage:
    py -3 scripts/dry_prompt.py math              # dry-run: 打印提示词
    py -3 scripts/dry_prompt.py math --live       # real smoke: 调 LLM 生成

验收标准：
    - stdout 含五块关键词：培养目标、真题锚点、RAG/跳过、迭代上下文、输出契约
    - 含 YAML 来源信息（ref_source）
    --live 模式下：
    - ref_source 非空
    - 题目非空
    - 不与锚点题干逐字相同（抽样比对前 80 字）
"""
from __future__ import annotations
import sys, os, json

# 确保能从项目根目录 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 加载 config 以注入 KB_PATH / lib 到 sys.path
import config  # noqa: F401


def _build_decision(subject: str):
    """构造一个用于 dry-run 的模拟决策对象。"""
    from intervention import InterventionDecision
    kp_map = {"math": "极限", "comm": "傅里叶级数", "review": "极限"}
    kp = kp_map.get(subject, "极限")
    return InterventionDecision("push", "intermediate", f"{kp}: 掌握度 45%，需出题练习", 3)


def dry_run(subject: str):
    """组装提示词并打印，不调 LLM。"""
    from prompts.prompt_builder import PromptBuilder
    from prompts.ref_picker import RefPicker

    topic_map = {
        "math": "数学一考研（教育部考试大纲；题型与难度对齐近年真题，教材体系同济高数/线代、浙大概率）",
        "comm": "北邮801通信原理（周炯槃教材第4版 Ch2–11，严格考纲范围）",
        "review": "错题巩固",
    }
    subject_map = {"math": "数学一", "comm": "通信原理", "review": "数学一（错题复盘）"}

    decision = _build_decision(subject)
    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    diff_map = {"basic": "基础", "intermediate": "中等", "challenge": "挑战"}
    act_map = {"push": "出题", "explain": "讲解概念", "review": "复诊错题", "defer": "", "escalate": ""}

    ref_entry = None
    ref_source = ""
    try:
        picker = RefPicker(subject)
        ref_entry = picker.pick(kp=kp, difficulty=decision.difficulty)
        if ref_entry:
            src = ref_entry.get("source", {})
            if isinstance(src, dict):
                ref_source = f"{src.get('year', '')}年{src.get('subject', '')}"
            else:
                ref_source = str(src)
    except Exception as e:
        print(f"[dry] RefPicker 跳过: {e}", file=sys.stderr)

    # RAG 硬契约（与 cultivate 同一入口）
    rag_items: list[dict] = []
    try:
        from learner.rag_retrieve import rag_retrieve

        rag = rag_retrieve(subject, kp, top_k=4, N=2)
        rag_items = rag.to_prompt_items()
        print(f"[dry] rag ok={rag.ok} hit={rag.hit_count} backend={rag.backend}", file=sys.stderr)
    except Exception as e:
        print(f"[dry] RAG 跳过: {e}", file=sys.stderr)

    from config import DATA_DIR
    from cultivate import _dynamic_style_pcts

    exam_pct, theory_pct = _dynamic_style_pcts(3, subject)

    builder = PromptBuilder()
    system, user = builder.build(
        subject_cn=subject_map.get(subject, subject),
        kp=kp,
        difficulty_cn=diff_map.get(decision.difficulty, "中等"),
        action_cn=act_map.get(decision.type, "出题"),
        reason=decision.reason,
        decision_type=decision.type,
        topic_desc=topic_map.get(subject, subject),
        mastery=0.45,
        opportunity_count=3,
        consecutive_failures=0,
        ref_entry=ref_entry,
        rag_items=rag_items,
        exam_style_pct=exam_pct,
        theory_extension_pct=theory_pct,
    )

    print("=" * 60)
    print("SYSTEM PROMPT")
    print("=" * 60)
    print(system)
    print()
    print("=" * 60)
    print("USER PROMPT")
    print("=" * 60)
    print(user)
    print()

    # 验收标记
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    checks = []
    # 五块关键词
    blocks = ["培养目标", "真题锚点", "迭代上下文", "输出契约", "风格比例"]
    for b in blocks:
        found = b in user
        mark = "OK" if found else "MISSING"
        checks.append(f"  {b}: {mark}")
    # RAG 或跳过
    if rag_items:
        checks.append(f"  RAG 辅助: OK ({rag_items[0].get('source', '?')})")
    else:
        checks.append("  RAG: skip (no hits)")
    # YAML 来源
    if ref_source:
        checks.append(f"  ref_source: {ref_source}")
    else:
        checks.append("  ref_source: none (YAML empty or no match)")

    for c in checks:
        print(c)

    # assert 模式供脚本调用检查
    all_ok = all("MISSING" not in c for c in checks)
    sys.exit(0 if all_ok else 1)


def live_run(subject: str):
    """真实 LLM 调用 smoke test。"""
    from bkt import BKTLogger
    from config import DATA_DIR
    from cultivate import assess_state, decide, generate, _get_consecutive_failures

    state = assess_state(subject)
    bkt_log = state["bkt_log"]
    decision = decide(subject, bkt_log)

    if decision.type == "defer":
        print(f"[live] {subject}: 跳过（{decision.reason}）")
        sys.exit(0)

    kp = decision.reason.split(":")[0] if ":" in decision.reason else decision.reason
    mastery = 0.0
    opportunity_count = 0
    try:
        if hasattr(bkt_log, 'get_kp_mastery'):
            kc = bkt_log.get_kp_mastery("wx_123", kp)
            if kc and hasattr(kc, 'p_mastery'):
                mastery = kc.p_mastery
            if kc and hasattr(kc, 'opportunity_count'):
                opportunity_count = kc.opportunity_count
    except Exception:
        pass
    consecutive_failures = _get_consecutive_failures("wx_123", bkt_log, kp)

    content = generate(
        subject, decision,
        mastery=mastery, opportunity_count=opportunity_count,
        consecutive_failures=consecutive_failures,
    )

    # 结果
    from cultivate import _last_answer, _last_ref_source
    print("=" * 60)
    print(f"LIVE SMOKE: {subject}")
    print("=" * 60)
    print(f"决策: {decision.type} / {decision.difficulty}")
    print(f"知识点: {kp}")
    print(f"掌握度: {mastery:.0%}")
    print(f"ref_source: {_last_ref_source}")
    print()
    print("--- 题目 ---")
    print(content[:500] if content else "(空)")
    print()
    if _last_answer:
        print("--- 答案 ---")
        print(_last_answer[:300])
    print()

    # 验收检查
    print("=" * 60)
    print("SMOKE VERIFICATION")
    print("=" * 60)

    ok = True

    # 1. ref_source 非空
    if _last_ref_source:
        print(f"  ref_source: OK ({_last_ref_source})")
    else:
        print("  ref_source: FAIL (empty)")
        ok = False

    # 2. 题目非空
    if content and len(content) > 20:
        print(f"  question: OK ({len(content)} chars)")
    else:
        print(f"  question: FAIL ({len(content)} chars)")
        ok = False

    # 3. 不与锚点题干逐字相同（抽样比对前 80 字）
    from prompts.ref_picker import RefPicker
    try:
        picker = RefPicker(subject)
        ref = picker.pick(kp=kp, difficulty=decision.difficulty)
        if ref and ref.get("question"):
            ref_prefix = ref["question"][:80].strip()
            gen_prefix = content[:80].strip()
            if ref_prefix and gen_prefix and ref_prefix == gen_prefix:
                print("  originality: FAIL (first 80 chars match anchor)")
                ok = False
            else:
                ref_preview = ref_prefix[:40].replace("\n", " ")
                gen_preview = gen_prefix[:40].replace("\n", " ")
                print(f"  originality: OK (anchor {ref_preview!r} vs gen {gen_preview!r})")
    except Exception as e:
        print(f"  原创性检查跳过: {e}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    subject = sys.argv[1] if len(sys.argv) > 1 else "math"
    if "--live" in sys.argv:
        live_run(subject)
    else:
        dry_run(subject)
