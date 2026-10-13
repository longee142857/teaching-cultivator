# -*- coding: utf-8 -*-
"""导入硬闸：界外 LaTeX 命令拒收；得证/薄步骤只警告。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WRAPPER = Path(ROOT) / "tool-scripts" / "tools" / "textbook-ingest" / "import_textbook.py"
CH7 = Path(ROOT) / "data" / "textbook_ingest" / "puheping_math_contest_v2" / "ch7"
SYLL_MATH = Path(ROOT) / "data" / "syllabus_math.json"
SYLL_COMM = Path(ROOT) / "data" / "syllabus_comm.json"

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def _bank(**kw):
    question = kw.pop("question", r"设 $A$ 满足 $\operatorname{rank}(A)=1$。")
    answer = kw.pop("answer", "1")
    sol = kw.pop(
        "solution",
        {
            "steps": [
                {"id": "s1", "text": "先看秩。"},
                {"id": "s2", "text": r"$\operatorname{rank}(A)=1$。"},
            ],
            "final_answer": answer,
            "techniques_used": ["秩"],
        },
    )
    cdps = kw.pop(
        "cdps",
        [
            {"id": "c1", "prompt": "秩是多少？", "expected": "1", "technique": "秩"},
            {"id": "c2", "prompt": "结论？", "expected": answer, "technique": "秩"},
        ],
    )
    return question, answer, sol, cdps


def test_operatorname_inside_dollars_passes() -> None:
    from math_format import bare_tex_commands, bare_tex_payload_error
    from learner.item_bank import validate_bank_payload

    samples = [
        r"$\operatorname{rank}(A)$",
        r"$\operatorname{rank}(A)=\operatorname{rank}(A \quad C)$",
        r"$$\begin{array}{l} a \\ \end{array}$$",
        r"\(\frac{1}{2}\)",
        r"\[\iint_D f \, dx\]",
        "见 $\\frac{1}{2}$ 即可。",
    ]
    for src in samples:
        cmds = bare_tex_commands(src)
        check(cmds == [], f"delimited ok {src!r} cmds={cmds}")

    question, answer, sol, cdps = _bank()
    err = bare_tex_payload_error(
        question=question, answer=answer, solution=sol, cdps=cdps
    )
    check(err == "", f"payload clean {err}")
    verr = validate_bank_payload(
        question=question,
        techniques=["秩"],
        solution=sol,
        cdps=cdps,
        answer=answer,
        check_math_delimiters=True,
    )
    check(verr == "", f"validate delimited {verr}")


def test_bare_command_and_begin_fail() -> None:
    from math_format import bare_tex_commands, bare_tex_payload_error
    from learner.item_bank import validate_bank_payload

    bare = r"f(x) = C\mathrm{e}^{\frac{1}{x}}$"
    cmds = bare_tex_commands(bare)
    check("\\mathrm" in cmds and "\\frac" in cmds, f"leading bare cmds {cmds}")
    # Inline $ does not cross a newline, so the command stays outside.
    multiline = "$\\frac{1}{2}\n+ 1$"
    check(bare_tex_commands(multiline), f"newline breaks inline $ {multiline!r}")
    check(bare_tex_commands(r"\begin{array}{l} a \end{array}"), "bare begin")
    # A closed pair must not hide a later bare command.
    shifted = r"C = 0$ 所以 $f(x) = x\mathrm{e}^x"
    check("\\mathrm" in bare_tex_commands(shifted), f"unclosed tail {shifted!r}")

    question, answer, sol, cdps = _bank(answer=r"\iint_D f\,dx")
    sol = dict(sol)
    sol["final_answer"] = answer
    sol["steps"] = [
        {"id": "s1", "text": "建立重积分。"},
        {"id": "s2", "text": r"\begin{array}{l} I \end{array}"},
    ]
    cdps = [
        {"id": "c1", "prompt": "区域？", "expected": "D", "technique": "秩"},
        {"id": "c2", "prompt": "结果？", "expected": answer, "technique": "秩"},
    ]
    err = bare_tex_payload_error(
        question=question, answer=answer, solution=sol, cdps=cdps
    )
    check(err.startswith("bare_tex:"), err)
    check("answer:" in err and "\\iint" in err, err)
    check("solution.final_answer:" in err, err)
    check("solution.steps[1].text:" in err and "\\begin{" in err, err)
    check("cdps[1].expected:" in err, err)
    verr = validate_bank_payload(
        question=question,
        techniques=["秩"],
        solution=sol,
        cdps=cdps,
        answer=answer,
        check_math_delimiters=True,
    )
    check(verr == err, f"validate matches {verr}")
    # Cultivate pregen does not opt in; structural checks still pass.
    off = validate_bank_payload(
        question=question,
        techniques=["秩"],
        solution=sol,
        cdps=cdps,
    )
    check(off == "", f"gate stays off by default {off}")


def test_stub_answer_and_thin_step_warn_only() -> None:
    from math_format import math_render_warnings
    from learner.item_bank import validate_bank_payload

    for stub in ("得证", "得证。", "证毕", "（略）", "见题解"):
        warns = math_render_warnings(
            answer=stub,
            solution={"steps": [{"id": "s1", "text": "所以"}, {"id": "s2", "text": "其通解为"}, {"id": "s3", "text": "这一步已经写完整。"}]},
        )
        check(warns[0] == "short_answer", f"{stub!r} -> {warns}")
        check("thin_step:0" in warns and "thin_step:1" in warns, warns)
        check("thin_step:2" not in warns, warns)
    long = math_render_warnings(
        answer="其中体积为 $V$，得证。",
        solution={"steps": [{"text": "所以物体排开水的重力等于浮力，得证。"}]},
    )
    check(long == [], f"prose ending 得证 is not a stub {long}")
    question, _answer, sol, cdps = _bank(answer="得证")
    sol = {
        "steps": [{"id": "s1", "text": "先证必要性。"}, {"id": "s2", "text": "所以"}],
        "final_answer": "得证",
        "techniques_used": ["秩"],
    }
    err = validate_bank_payload(
        question=question,
        techniques=["秩"],
        solution=sol,
        cdps=cdps,
        answer="得证",
        check_math_delimiters=True,
    )
    check(err == "", f"stub must not hard-fail {err}")


def _textbook_fixture(**over) -> dict:
    item = {
        "id": "tx-pu-bare-tex-fixture",
        "subject": "math",
        "l2": "函数极限与连续",
        "l3_id": "math.calc.limit.compute",
        "atom_id": "",
        "book_id": "",
        "ability_goal": "compute",
        "item_form": "blank",
        "difficulty": "hit",
        "question": "求 $\\lim_{x\\to 0}(1-\\cos x)/x^{2}$。",
        "answer": "\\frac{1}{2}",
        "techniques": ["等价无穷小"],
        "solution": {
            "steps": [
                {"id": "s1", "text": "用等价替换。"},
                {"id": "s2", "text": "得到 $\\frac{1}{2}$。"},
            ],
            "final_answer": "\\frac{1}{2}",
            "techniques_used": ["等价无穷小"],
        },
        "cdps": [
            {
                "id": "c1",
                "prompt": "主部？",
                "expected": "$1-\\cos x\\sim x^{2}/2$",
                "technique": "等价无穷小",
                "depends_on": [],
            },
            {
                "id": "c2",
                "prompt": "极限？",
                "expected": "\\frac{1}{2}",
                "technique": "等价无穷小",
                "depends_on": ["c1"],
            },
        ],
        "meta": {
            "source": "textbook_example",
            "book_id": "puheping_math_contest_v2",
            "quality_basis": "textbook_original",
        },
    }
    item.update(over)
    return item


def _dry(incoming: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--incoming",
            str(incoming),
            "--syllabus-math",
            str(SYLL_MATH),
            "--syllabus-comm",
            str(SYLL_COMM),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def test_import_dry_run_rejects_bare_tex_fixture() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "tx-pu-bare-tex-fixture.json"
        path.write_text(json.dumps(_textbook_fixture(), ensure_ascii=False), encoding="utf-8")
        rc, out = _dry(Path(td))
    check(rc != 0, f"bare fixture rc={rc} {out[-600:]}")
    check("payload:bare_tex:" in out, out[-800:])
    check("answer:" in out and "\\frac" in out, out[-800:])
    check("MCQ" not in out, out[-400:])


def test_import_dry_run_accepts_delimited_rank() -> None:
    item = _textbook_fixture(
        question=r"证明 $\operatorname{rank}(A)=\operatorname{rank}(A \quad C)$。",
        answer=r"$\operatorname{rank}(A)=\operatorname{rank}(B)$",
        solution={
            "steps": [
                {"id": "s1", "text": "比较列空间。"},
                {"id": "s2", "text": r"故 $\operatorname{rank}(A)=\operatorname{rank}(B)$。"},
            ],
            "final_answer": r"$\operatorname{rank}(A)=\operatorname{rank}(B)$",
            "techniques_used": ["等价无穷小"],
        },
        cdps=[
            {
                "id": "c1",
                "prompt": r"$\operatorname{rank}(A)$ 与增广矩阵的关系？",
                "expected": "列空间一致",
                "technique": "等价无穷小",
                "depends_on": [],
            },
            {
                "id": "c2",
                "prompt": "结论？",
                "expected": r"$\operatorname{rank}(A)=\operatorname{rank}(B)$",
                "technique": "等价无穷小",
                "depends_on": ["c1"],
            },
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "tx-pu-bare-tex-fixture.json"
        path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        rc, out = _dry(Path(td))
    check(rc == 0, f"delimited rank rc={rc} {out[-800:]}")
    check("DRY" in out, out[-400:])
    check("payload:bare_tex:" not in out, out[-400:])
    check("MCQ" not in out, out[-400:])


def test_ch7_answers_have_no_bare_tex() -> None:
    from math_format import bare_tex_commands

    files = [
        p
        for p in CH7.rglob("*.json")
        if p.name != "MANIFEST.json" and not p.name.endswith(".example.json")
    ]
    check(len(files) == 58, f"ch7 count {len(files)}")
    bad = []
    for path in files:
        item = json.loads(path.read_text(encoding="utf-8"))
        for label, text in (
            ("answer", item.get("answer")),
            ("final_answer", (item.get("solution") or {}).get("final_answer")),
        ):
            cmds = bare_tex_commands(text if isinstance(text, str) else "")
            if cmds:
                bad.append(f"{path.name}:{label}:{cmds[:3]}")
        for i, step in enumerate((item.get("solution") or {}).get("steps") or []):
            text = step.get("text") if isinstance(step, dict) else ""
            cmds = bare_tex_commands(text if isinstance(text, str) else "")
            if cmds:
                bad.append(f"{path.name}:step{i}:{cmds[:3]}")
        for i, cdp in enumerate(item.get("cdps") or []):
            if not isinstance(cdp, dict):
                continue
            for key in ("prompt", "expected"):
                cmds = bare_tex_commands(cdp.get(key) if isinstance(cdp.get(key), str) else "")
                if cmds:
                    bad.append(f"{path.name}:cdp{i}.{key}:{cmds[:3]}")
    check(not bad, f"ch7 still bare {bad[:6]}")


def test_ch7_import_dry_run_passes() -> None:
    check(CH7.is_dir(), "ch7 dir")
    rc, out = _dry(CH7)
    check(rc == 0, f"ch7 dry-run rc={rc} {out[-800:]}")
    check("failed=0" in out, out[-300:])
    check("imported=58" in out, out[-300:])
    check("payload:bare_tex:" not in out, out[-400:])


def main() -> int:
    test_operatorname_inside_dollars_passes()
    test_bare_command_and_begin_fail()
    test_stub_answer_and_thin_step_warn_only()
    test_import_dry_run_rejects_bare_tex_fixture()
    test_import_dry_run_accepts_delimited_rank()
    test_ch7_answers_have_no_bare_tex()
    test_ch7_import_dry_run_passes()
    print("fails", _fails)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
