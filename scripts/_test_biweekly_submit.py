# -*- coding: utf-8 -*-
"""biweekly exam submit edge-case tests (no live LLM required)."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import patch

# repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner import biweekly_exam as be


def sep(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def expect(cond: bool, msg: str):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {msg}")
        if not cond:
            fails += 1

    sep("1. empty / whitespace → 不进批改")
    r1 = be.submit_answer_md("")
    r2 = be.submit_answer_md("   \n\t\n  ")
    check("答卷为空" in r1, f"empty: {r1[:80]}")
    check("答卷为空" in r2, f"whitespace: {r2[:80]}")

    sep("2. 无 paper_id、无题库命中时")
    # 可能落到最近试卷；至少不应崩溃
    try:
        r = be.submit_answer_md("没有试卷元信息的胡写内容")
        check(isinstance(r, str) and len(r) > 0, f"no-id returns str: {r[:120]}")
        check("异常" not in r or "批改异常" in r, "no uncaught crash text")
    except Exception as e:
        check(False, f"raised: {e}")

    sep("3. 解析：标准作答区 / 第N题答案")
    md_zones = """# 答卷
### 作答区 1
```
A
```
### 作答区 2
```
证明：略
```
- paper_id: 2026-07-20_math
"""
    check(be._extract_paper_id(md_zones) == "2026-07-20_math", "extract paper_id")
    z = be._parse_answers_from_md(md_zones)
    check(z.get(1) == "A" and z.get(2) == "证明：略", f"parse zones: {z}")

    md_alt = """
第 1 题答案：B
第 2 题作答：极限为 0
paper_id: 2099-01-01_comm
"""
    check(be._extract_paper_id(md_alt) == "2099-01-01_comm", "extract alt")
    a = be._parse_answers_from_md(md_alt)
    check(a.get(1) == "B" and "极限" in (a.get(2) or ""), f"parse alt: {a}")

    sep("4. seed fake paper")
    pid = "2099-01-01_math"
    be._ensure_dirs()
    items = [
        {
            "l2": "函数极限与连续",
            "l3_id": "math.calc.limit.def",
            "ability": "recognize",
            "item_form": "mcq",
            "question": "下列哪个是极限定义？\n(A) 1 (B) 2 (C) 3 (D) 4",
            "answer": "A",
        },
        {
            "l2": "函数极限与连续",
            "l3_id": "math.calc.limit.equiv",
            "ability": "compute",
            "item_form": "blank",
            "question": "求 lim x->0 sinx/x = ____",
            "answer": "1",
        },
    ]
    paper = {
        "paper_id": pid,
        "subject": "math",
        "title": "数学一",
        "created_at": datetime.now().isoformat(),
        "items": items,
        "public_md": be._render_public_md(pid, "数学一", "math", items),
        "n_ok": 2,
        "n_target": 2,
    }
    be.persist_paper(paper)
    print("seeded", pid)

    sep("4a. 只有 paper_id、无作答区 → 拒绝批改")
    bare = f"# 空答卷\n\n- paper_id: {pid}\n- subject: math\n"
    r = be.submit_answer_md(bare)
    check("未解析到任何作答区" in r, f"bare: {r[:200]}")
    check("判对" not in r, "bare should not claim graded score")

    sep("4b. 空代码块作答区 → 记未作答，不调 LLM 假正确")
    empty_blocks = f"""# 答卷
## 第 1 题
### 作答区 1
```

```
## 第 2 题
### 作答区 2
```

```
- paper_id: {pid}
"""
    pe = be._parse_answers_from_md(empty_blocks)
    check(1 in pe and 2 in pe and pe[1] == "" and pe[2] == "", f"empty fences parse: {pe}")
    with patch("grade.grade_answer") as mock_g:
        mock_g.side_effect = AssertionError("LLM should not be called for empty answers")
        r = be.submit_answer_md(empty_blocks)
    check("未作答" in r, f"empty fences grade: {r[:300]}")
    check("非空作答：0/2" in r or "0/2" in r, f"zero answered: {r[:200]}")
    check("判对（启发式）：0/2" in r, "zero correct")

    sep("4c. 只答一题（mock grade）")
    partial = f"""# 答卷
### 作答区 1
```
A
```
- paper_id: {pid}
"""
    with patch("grade.grade_answer", return_value="正确。选择 A。"):
        r = be.submit_answer_md(partial)
    check("未作答" in r, "q2 unanswered")
    check("非空作答：1/2" in r, f"partial count: {r[:250]}")
    check("判对（启发式）：1/2" in r, "one correct heuristic")

    sep("4d. 错误 paper_id")
    r = be.submit_answer_md("随便写点", paper_id="1999-01-01_math")
    check("找不到试卷密钥" in r, f"wrong id: {r}")

    sep("4e. 两题齐全（mock，含『不正确』不误判为对）")
    full = f"""# 答卷
### 作答区 1
```
A
```
### 作答区 2
```
2
```
- paper_id: {pid}
"""

    def fake_grade(q, a):
        if "sinx" in q or "____" in q or "limit" in q.lower() or "lim" in q.lower():
            return "不正确。应为 1。"
        return "正确。选择 A。"

    with patch("grade.grade_answer", side_effect=fake_grade):
        r = be.submit_answer_md(full)
    check("非空作答：2/2" in r, f"full answered: {r[:300]}")
    check("判对（启发式）：1/2" in r, f"one correct despite 不正确: {r[:400]}")

    sep("4f. grade 抛异常 → 不整卷崩溃")
    with patch("grade.grade_answer", side_effect=RuntimeError("llm down")):
        r = be.submit_answer_md(full)
    check("批改异常" in r, f"exception handled: {r[:400]}")
    check("第1题" in r and "第2题" in r, "still reports both items")

    sep("5. get_exam_paper")
    g = be.get_exam_paper(pid)
    check(pid in g and "第 1 题" in g, "paper body ok")
    check("未找到试卷" in be.get_exam_paper("no-such-paper"), "missing paper")

    sep("6. 仅「交卷」正文剥离后的空串语义（同 bot）")
    check("答卷为空" in be.submit_answer_md(""), "empty after strip")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL EDGE TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
