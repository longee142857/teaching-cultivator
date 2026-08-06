# -*- coding: utf-8 -*-
"""试卷按人存卷/分数/kp 映射/草稿/身份交换 边界测试（临时 data 目录，不碰真实数据）。"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner import biweekly_exam as be
from grade import GradeResult


def _gr(text="正确。", correct=True):
    return GradeResult(
        is_correct=correct,
        feedback=text,
        kp_name="函数极限与连续",
        subject="math",
        p_mastery_before=0.2,
        p_mastery_after=0.35,
        credit=None,
        item_type="blank",
        status="applied",
        confidence=1.0,
    )


def seed(pid="2099-02-02_math"):
    items = [
        {
            "l2": "函数极限与连续",
            "l3_id": "math.calc.limit.def",
            "ability": "compute",
            "item_form": "blank",
            "question": "求 lim sinx/x = ____",
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
        "n_ok": 1,
        "n_target": 1,
    }
    be.persist_paper(paper)
    return pid


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    with tempfile.TemporaryDirectory() as td:
        be.BANK_DIR = os.path.join(td, "exam_bank")
        be.PAPERS_DIR = os.path.join(be.BANK_DIR, "papers")
        be.KEYS_DIR = os.path.join(be.BANK_DIR, "keys")
        be.ANSWERS_DIR = os.path.join(be.BANK_DIR, "answers")
        be.INDEX_PATH = os.path.join(be.BANK_DIR, "index.json")
        be.STATE_PATH = os.path.join(be.BANK_DIR, "state.json")

        pid = seed()
        md = f"""# 答卷
### 作答区 1
```
1
```
- paper_id: {pid}
"""

        print("=== 1. 按人存卷 + 分数 + kp/subject 传参 ===")
        seen_kwargs = {}

        def fake_grade(q, a, **kw):
            seen_kwargs.update(kw)
            return _gr()

        with patch("grade.grade_answer", side_effect=fake_grade):
            r = be.submit_answer_md(md, paper_id=pid, user_id="staff_a")
        check(seen_kwargs.get("kp_name") == "函数极限与连续", f"kp passed: {seen_kwargs}")
        check(seen_kwargs.get("subject") == "math", "subject passed")
        check("**得分：100/100**" in r, f"score line: {r[:120]}")
        check("掌握 20%→35%" in r, "mastery before/after shown")

        fa = os.path.join(be.ANSWERS_DIR, f"{pid}_staff_a_answer.md")
        fg = os.path.join(be.ANSWERS_DIR, f"{pid}_staff_a_grade.md")
        check(os.path.isfile(fa) and os.path.isfile(fg), "per-user files written")

        print("=== 2. 不同 uid 独立 ===")
        with patch("grade.grade_answer", return_value=_gr()):
            be.submit_answer_md(md, paper_id=pid, user_id="staff_b")
        check(
            os.path.isfile(os.path.join(be.ANSWERS_DIR, f"{pid}_staff_b_grade.md")),
            "staff_b file exists",
        )
        check(
            not os.path.isfile(os.path.join(be.ANSWERS_DIR, f"{pid}_staff_c_grade.md")),
            "staff_c absent",
        )

        print("=== 3. get_exam_result 工具（agent）===")
        from agent.tools import get_exam_result

        out = get_exam_result(pid, user_id="staff_a")
        check("批改报告" in out and "得分" in out, "agent result has report+score")
        check("你的作答" in out, "agent result has user answers")
        out_miss = get_exam_result(pid, user_id="nobody")
        check("没有该学员的批改记录" in out_miss, "missing result handled")

        print("=== 4. 草稿端点 helper（exam_web）===")
        import deliver.exam_web as ew

        ew_drafts = os.path.join(be.BANK_DIR, "drafts")

        def _fake_drafts_dir():
            return ew_drafts

        ew.drafts_dir = _fake_drafts_dir
        ok = ew.save_draft(pid, "staff_a", {"1": "写了一半"})
        check(ok and os.path.isfile(ew._draft_path(pid, "staff_a")), "draft saved")
        d = ew.load_draft(pid, "staff_a")
        check(d.get("answers", {}).get("1") == "写了一半", "draft loaded")
        ew.clear_draft(pid, "staff_a")
        check(not os.path.isfile(ew._draft_path(pid, "staff_a")), "draft cleared")
        p2 = ew._draft_path(pid, "ab/CD 中")
        base = os.path.basename(p2)
        check(
            "/" not in base and "\\" not in base and "中" not in base and "_abCD" in base,
            f"uid sanitized: {base}",
        )

        print("=== 5. authCode 空 → 返回空（前端降级设备 UUID）===")
        check(ew._exchange_auth_code("") == "", "empty authCode -> ''")
        check(ew._exchange_auth_code(None) == "", "None authCode -> ''")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL EXAM PERSONAL TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
