# -*- coding: utf-8 -*-
"""双周卷发卷格式 + 大题化 边界测试（无 LLM）。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner.ability_cycle import (
    exam_item_form,
    parse_item_form_from_reason,
    ability_to_item_form,
)
from learner import biweekly_exam as be


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    print("=== exam_item_form ===")
    check(exam_item_form("recognize") == "blank", "recognize→blank")
    check(exam_item_form("diagnose") == "blank", "diagnose→blank")
    check(exam_item_form("compute") == "blank", "compute→blank")
    check(exam_item_form("construct") == "proof_outline", "construct→proof")
    check(exam_item_form("transfer") == "proof_outline", "transfer→proof")
    # 日常仍可出选择题
    check(ability_to_item_form("recognize") == "mcq", "daily recognize still mcq")

    print("=== parse_item_form_from_reason ===")
    check(
        parse_item_form_from_reason("x [item_form=blank] y") == "blank",
        "parse blank",
    )
    check(
        parse_item_form_from_reason("x [item_form=proof_outline]") == "proof_outline",
        "parse proof",
    )
    check(parse_item_form_from_reason("no tag") is None, "no tag")

    print("=== mcq detector ===")
    mcq = "选\nA. 1\nB. 2\nC. 3\nD. 4"
    check(be._looks_like_mcq(mcq) is True, "detect mcq")
    check(be._looks_like_mcq("求 lim x→0 sinx/x = ____") is False, "blank not mcq")
    check(be._looks_like_mcq("求证：f 连续。写出证明。") is False, "proof not mcq")

    print("=== dingtalk chunks（无 .md 附件语义）===")
    paper = {
        "paper_id": "2099-07-28_math",
        "title": "数学一",
        "items": [
            {
                "item_form": "blank",
                "ability": "compute",
                "question": "计算 $$\\int_0^1 x dx$$ = ____",
            },
            {
                "item_form": "proof_outline",
                "ability": "construct",
                "question": "求证：……",
            },
        ],
    }
    chunks = be.render_dingtalk_chunks(paper)
    check(len(chunks) == 3, f"cover+2q = {len(chunks)}")
    check("不再发送" in chunks[0] and ".md" in chunks[0], "cover mentions no md attach")
    check("第 1/2 题" in chunks[1] and "填空" in chunks[1], "q1 chunk")
    check("paper_id: 2099-07-28_math" in chunks[1], "paper_id in q chunk")
    check("证明" in chunks[2], "q2 proof label")

    md = be._render_public_md("2099-07-28_math", "数学一", "math", paper["items"])
    check("推送" in md and "H5 链接" in md, "archive md notes dingtalk push")
    check("### 作答区 1" in md, "answer zones kept for submit")

    print("=== EXAM abilities pool ===")
    check("recognize" not in be._EXAM_ABILITIES, "no recognize in exam pool")
    check("diagnose" not in be._EXAM_ABILITIES, "no diagnose in exam pool")

    if fails:
        print(f"FAILED {fails}")
        sys.exit(1)
    print("ALL PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
