# -*- coding: utf-8 -*-
"""教材例题入库：dry-run 扫 textbook_ingest；不自动 pass workshop。"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

IMPORTER = Path(ROOT) / "tool-scripts" / "tools" / "bank-workshop" / "import_incoming.py"
WRAPPER = Path(ROOT) / "tool-scripts" / "tools" / "textbook-ingest" / "import_textbook.py"
TEXTBOOK_DIR = Path(ROOT) / "data" / "textbook_ingest" / "puheping_math_contest_v2"
SYLL_MATH = Path(ROOT) / "data" / "syllabus_math.json"
SYLL_COMM = Path(ROOT) / "data" / "syllabus_comm.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def _textbook_item(**kw) -> dict:
    item = {
        "id": "tx-pu-limit-compute-fixture",
        "subject": "math",
        "l2": "函数极限与连续",
        "l3_id": "math.calc.limit.compute",
        "atom_id": "",
        "book_id": "",
        "ability_goal": "compute",
        "item_form": "blank",
        "difficulty": "hit",
        "question": "求 lim_{x→0} (1 − cos x) / x²。",
        "answer": "1/2",
        "techniques": ["等价无穷小", "泰勒展开"],
        "solution": {
            "steps": [
                {"id": "s1", "text": "1−cos x ~ x²/2（x→0）。"},
                {"id": "s2", "text": "代入得 1/2。"},
            ],
            "final_answer": "1/2",
            "techniques_used": ["等价无穷小", "泰勒展开"],
        },
        "cdps": [
            {
                "id": "cdp1",
                "prompt": "写出 1−cos x 的等价主部。",
                "expected": "1−cos x ~ x²/2。",
                "technique": "等价无穷小",
                "depends_on": [],
            },
            {
                "id": "cdp2",
                "prompt": "代入求极限。",
                "expected": "1/2。",
                "technique": "泰勒展开",
                "depends_on": ["cdp1"],
            },
        ],
        "meta": {
            "source": "textbook_example",
            "book_id": "puheping_math_contest_v2",
            "quality_basis": "textbook_original",
        },
    }
    item.update(kw)
    return item


def _workshop_item(**kw) -> dict:
    item = _textbook_item()
    item["id"] = "ws-math-not-auto-pass"
    item["meta"] = {"source": "cloud_cursor_workshop"}
    item.update(kw)
    return item


def test_catalog_dir_dry_run_scans() -> None:
    check(TEXTBOOK_DIR.is_dir(), f"catalog dir exists {TEXTBOOK_DIR}")
    check((TEXTBOOK_DIR / "schema.example.json").is_file(), "schema.example.json present")
    proc = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--incoming",
            str(TEXTBOOK_DIR),
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
    out = (proc.stdout or "") + (proc.stderr or "")
    check(proc.returncode == 0, f"catalog dry-run rc={proc.returncode} {out[-800:]}")
    check("mode=dry-run" in out, f"dry-run banner {out[:400]}")
    check(str(TEXTBOOK_DIR) in out, f"incoming path printed {out[:400]}")
    check("imported=0" in out, f"example json not imported {out[-400:]}")
    check("catalog example" in out, f"notes skipped example {out}")


def test_mapping_tags_and_keeps_ref_source() -> None:
    imp = _load("import_incoming", IMPORTER)
    kwargs, err = imp.item_to_bank_kwargs(_textbook_item())
    check(err == "", f"map ok {err}")
    assert kwargs is not None
    check(kwargs["kp"] == "函数极限与连续", kwargs["kp"])
    check(kwargs["l3_id"] == "math.calc.limit.compute", kwargs["l3_id"])
    check(kwargs["atom_id"] == "", "math atom_id may be empty")
    check(kwargs["meta"]["source"] == "textbook_example", kwargs["meta"])
    check(kwargs["meta"]["book_id"] == "puheping_math_contest_v2", kwargs["meta"])
    check(kwargs["ref_source"] == "textbook:puheping_math_contest_v2", kwargs["ref_source"])
    check(kwargs["meta"].get("quality_basis") == "textbook_original", kwargs["meta"])

    kept = _textbook_item(ref_source="textbook:custom_keep")
    kwargs2, err2 = imp.item_to_bank_kwargs(kept)
    check(err2 == "", err2)
    assert kwargs2 is not None
    check(kwargs2["ref_source"] == "textbook:custom_keep", kwargs2["ref_source"])

    bad_id = _textbook_item(id="not-a-tx-pu-id")
    _kw, err3 = imp.item_to_bank_kwargs(bad_id)
    check("textbook_id_prefix" in (err3 or ""), err3)


def test_workshop_without_judge_is_not_auto_pass() -> None:
    imp = _load("import_incoming", IMPORTER)
    item = _workshop_item()
    check(not imp.is_textbook_item(item), "workshop is not textbook")
    reason = imp.classify_skip(item, None, Path("/tmp/missing.judge.json"))
    check(reason == "no_judge", f"workshop skip={reason}")

    tb = _textbook_item()
    reason_tb = imp.classify_skip(tb, None, Path("/tmp/missing.judge.json"))
    check(reason_tb == "", f"textbook no judge skip={reason_tb}")


def test_cli_dry_run_and_temp_apply() -> None:
    from learner.db import Store, reset_store

    with tempfile.TemporaryDirectory() as td:
        incoming = Path(td) / "ch1"
        incoming.mkdir()
        (incoming / "tx-pu-limit-compute-fixture.json").write_text(
            json.dumps(_textbook_item(), ensure_ascii=False),
            encoding="utf-8",
        )
        (incoming / "ws-workshop.json").write_text(
            json.dumps(_workshop_item(), ensure_ascii=False),
            encoding="utf-8",
        )
        dry = subprocess.run(
            [
                sys.executable,
                str(IMPORTER),
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
        out = (dry.stdout or "") + (dry.stderr or "")
        check(dry.returncode == 0, f"mixed dry-run rc={dry.returncode} {out[-800:]}")
        check("DRY" in out and "textbook_example" in out, f"textbook DRY {out}")
        check("SKIP" in out and "no_judge" in out, f"workshop skipped {out}")
        check("cloud_cursor_workshop" not in out.split("DRY")[-1] or "SKIP" in out, "workshop not DRY-passed")

        fd, dbp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["TEACHING_DB"] = dbp
        reset_store()
        try:
            apply = subprocess.run(
                [
                    sys.executable,
                    str(IMPORTER),
                    "--incoming",
                    str(incoming),
                    "--apply",
                    "--db",
                    dbp,
                    "--no-move",
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
            aout = (apply.stdout or "") + (apply.stderr or "")
            check(apply.returncode == 0, f"apply rc={apply.returncode} {aout[-800:]}")
            store = Store(dbp)
            row = store.get_item_by_question("求 lim_{x→0} (1 − cos x) / x²。", "math")
            check(row is not None, "textbook row exists")
            check((row.get("meta") or {}).get("source") == "textbook_example", row.get("meta"))
            check(row.get("ref_source") == "textbook:puheping_math_contest_v2", row.get("ref_source"))
            check(row.get("kp") == "函数极限与连续", row.get("kp"))
            check(row.get("l3_id") == "math.calc.limit.compute", row.get("l3_id"))
            check(not (row.get("atom_id") or ""), row.get("atom_id"))
            check(row.get("quality_tier") == "pass", row.get("quality_tier"))
            check((row.get("meta") or {}).get("book_id") == "puheping_math_contest_v2", row.get("meta"))
        finally:
            os.environ.pop("TEACHING_DB", None)
            reset_store()
            try:
                os.remove(dbp)
            except OSError:
                pass


def main() -> int:
    test_catalog_dir_dry_run_scans()
    test_mapping_tags_and_keeps_ref_source()
    test_workshop_without_judge_is_not_auto_pass()
    test_cli_dry_run_and_temp_apply()
    print("fails", _fails)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
