# -*- coding: utf-8 -*-
"""kp_edit 提案→确认→落盘 边界测试（临时考纲，不碰真实 data）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from learner import kp_edit, kp_registry


def make_syllabus() -> dict:
    return {
        "subject": "math",
        "l1": {"calc": {"name": "微积分"}},
        "kps": {
            "函数极限与连续": {
                "l1": "calc",
                "scope": "函数、极限、连续",
                "aliases": ["极限", "连续"],
                "l3": [
                    {
                        "id": "math.calc.limit.def",
                        "name": "极限的ε-N定义",
                        "aliases": ["ε-N", "极限定义"],
                        "rag_queries": ["极限定义"],
                        "source_allow": ["教材", "真题"],
                    },
                    {
                        "id": "math.calc.limit.equiv",
                        "name": "极限的等价定义",
                        "aliases": [],
                        "rag_queries": ["等价定义"],
                        "source_allow": ["教材"],
                    },
                ],
            },
            "导数与微分": {
                "l1": "calc",
                "scope": "导数、微分",
                "aliases": ["导数"],
                "l3": [
                    {
                        "id": "math.calc.diff.def",
                        "name": "导数的定义",
                        "aliases": ["导数定义"],
                        "rag_queries": ["导数定义"],
                        "source_allow": ["教材"],
                    },
                ],
            },
        },
    }


def main():
    fails = 0

    def check(cond: bool, msg: str):
        nonlocal fails
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[{'PASS' if cond else 'FAIL'}] {safe}")
        if not cond:
            fails += 1

    with tempfile.TemporaryDirectory() as td:
        syl_path = os.path.join(td, "syllabus_math.json")
        with open(syl_path, "w", encoding="utf-8") as f:
            json.dump(make_syllabus(), f, ensure_ascii=False, indent=2)
        kp_registry.SYLLABUS_PATHS = {
            "math": syl_path,
            "comm": os.path.join(td, "syllabus_comm.json"),
        }
        kp_registry.reload_registry()
        kp_edit.PROPOSALS_PATH = os.path.join(td, "kp_proposals.json")
        kp_edit.AUDIT_PATH = os.path.join(td, "kp_edit_audit.jsonl")

        def l3_count() -> int:
            with open(syl_path, encoding="utf-8") as f:
                cur = json.load(f)
            return len(cur["kps"]["函数极限与连续"]["l3"])

        print("=== 1. 校验 ===")
        r = kp_edit.propose_l3("phy", "极限", "xx")
        check(not r.get("ok") and "科目" in r.get("error", ""), f"invalid subject: {r}")

        r = kp_edit.propose_l3("math", "", "xx")
        check(not r.get("ok") and "章节" in r.get("error", ""), "empty l2")

        r = kp_edit.propose_l3("math", "不存在的章节", "xx")
        check(not r.get("ok") and "不存在" in r.get("error", ""), f"missing l2: {r}")

        r = kp_edit.propose_l3("math", "函数极限与连续", "极限的ε-N定义")
        check(not r.get("ok") and "已存在" in r.get("error", ""), f"dup by name: {r}")

        r = kp_edit.propose_l3("math", "函数极限与连续", "夹逼定理", aliases=["极限定义"])
        check(not r.get("ok") and "别名" in r.get("error", ""), f"dup by alias: {r}")

        print("=== 2. 合法提案（l3_id 自动生成）===")
        r = kp_edit.propose_l3(
            "math", "函数极限与连续", "夹逼定理", aliases=["迫敛性", "挤压定理"],
            staff_id="staff1",
        )
        check(r.get("ok"), f"propose ok: {r}")
        check(
            r.get("l3_id", "").startswith("math.calc.limit.") and r["l3_id"].endswith(".k1"),
            f"l3_id derived: {r.get('l3_id')}",
        )
        token = r["token"]
        l3_id = r["l3_id"]

        print("=== 3. 未确认前不写入 ===")
        check(l3_count() == 2, f"not written before confirm (count={l3_count()})")

        print("=== 4. staff 校验 ===")
        r = kp_edit.confirm_l3(token, staff_id="other")
        check(not r.get("ok") and "不是" in r.get("error", ""), f"staff mismatch: {r}")

        print("=== 5. 确认写入 ===")
        r = kp_edit.confirm_l3(token, staff_id="staff1")
        check(r.get("ok"), f"confirm ok: {r}")
        check(l3_count() == 3, f"l3 grown to 3 (count={l3_count()})")
        with open(syl_path, encoding="utf-8") as f:
            cur = json.load(f)
        written = [
            x for x in cur["kps"]["函数极限与连续"]["l3"]
            if isinstance(x, dict) and x.get("id") == l3_id
        ]
        check(
            bool(written) and written[0].get("name") == "夹逼定理"
            and written[0].get("aliases") == ["迫敛性", "挤压定理"],
            f"l3 written: {written}",
        )

        print("=== 6. 重复确认 / 校验后写入 ===")
        r = kp_edit.confirm_l3(token, staff_id="staff1")
        check(not r.get("ok") and "已处理" in r.get("error", ""), f"double confirm: {r}")

        # 别名经 resolve 归到标准 L2
        r = kp_edit.propose_l3("math", "极限", "保号性", staff_id="staff1")
        check(r.get("ok") and r.get("l2") == "函数极限与连续", f"l2 via alias resolve: {r}")

        print("=== 7. 取消 ===")
        r = kp_edit.propose_l3("math", "函数极限与连续", "闭区间套定理", staff_id="staff1")
        token2 = r["token"]
        r = kp_edit.cancel_l3(token2, staff_id="staff1")
        check(r.get("ok"), f"cancel ok: {r}")
        r = kp_edit.confirm_l3(token2, staff_id="staff1")
        check(not r.get("ok") and "已处理" in r.get("error", ""), f"confirm after cancel: {r}")
        check(l3_count() == 3, f"cancelled not written (count={l3_count()})")

        print("=== 8. l3_id 递增不撞 ===")
        r1 = kp_edit.propose_l3("math", "函数极限与连续", "Heine定理", staff_id="")
        r2 = kp_edit.propose_l3("math", "函数极限与连续", "柯西收敛准则", staff_id="")
        check(r1.get("ok") and r2.get("ok"), f"propose r1/r2 ok")

        def _knum(l3_id: str) -> int:
            return int(l3_id.rsplit(".k", 1)[-1])

        check(
            r1["l3_id"] != r2["l3_id"]
            and _knum(r1["l3_id"]) < _knum(r2["l3_id"]),
            f"ids distinct & incremented: {r1['l3_id']} vs {r2['l3_id']}",
        )
        check(
            r1["l3_id"].startswith("math.calc.limit.") and r2["l3_id"].startswith("math.calc.limit."),
            f"prefix preserved: {r1['l3_id']} {r2['l3_id']}",
        )

        print("=== 9. 审计日志 ===")
        check(os.path.isfile(kp_edit.AUDIT_PATH), "audit file exists")
        with open(kp_edit.AUDIT_PATH, encoding="utf-8") as f:
            kinds = [json.loads(ln)["kind"] for ln in f if ln.strip()]
        check("propose" in kinds and "confirm" in kinds and "cancel" in kinds,
              f"audit kinds: {kinds}")

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {fails} FAIL(s)")
        sys.exit(1)
    print("ALL KP_EDIT TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
