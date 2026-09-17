# -*- coding: utf-8 -*-
"""工坊校验 / 导入：拒 review、硬闸 atom、写入 meta.source。"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
WS = Path(ROOT) / "data" / "bank_workshop"


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


def _syll() -> dict:
    return {
        "math.calc.limit.def": {"l2": "极限", "l3_name": "定义", "subject": "math"},
        "comm.sig_rand.fourier.transform": {
            "l2": "确定信号与频谱分析",
            "l3_name": "FT",
            "subject": "comm",
        },
    }


def _math_item(**kw) -> dict:
    item = {
        "id": "ws-math-1",
        "subject": "math",
        "l2": "极限",
        "l3_id": "math.calc.limit.def",
        "atom_id": "",
        "book_id": "",
        "ability_goal": "compute",
        "item_form": "blank",
        "difficulty": "hit",
        "question": "求 lim x→0 sinx/x",
        "answer": "1",
        "techniques": ["等价无穷小", "夹逼"],
        "solution": "用等价无穷小得 1。",
        "cdps": 2,
        "meta": {"source": "cloud_cursor_workshop"},
    }
    item.update(kw)
    return item


def test_validate_rejects_review_and_comm_without_atom() -> None:
    val = _load("validate_incoming", WS / "validate_incoming.py")
    syll = _syll()
    review = _math_item(subject="review", id="ws-rev")
    errs = val.check_item(review, syll, False, None)
    check(any("review" in e for e in errs), f"reject review {errs}")

    comm = _math_item(
        subject="comm",
        l2="确定信号与频谱分析",
        l3_id="comm.sig_rand.fourier.transform",
        atom_id="",
        book_id="zhou_comm",
        id="ws-comm-miss",
    )
    errs2 = val.check_item(comm, syll, False, None)
    check(any("atom_id" in e for e in errs2), f"comm requires atom {errs2}")


def test_ingest_dry_run_and_apply_pass() -> None:
    ingest = _load("ingest_incoming", WS / "ingest_incoming.py")
    item = _math_item()
    judge = {"decision": "accept", "reasons": ["ok"]}
    dry = ingest.import_one(item, judge, apply=False, require_judge_accept=True)
    check(dry.get("dry_run") is True, f"dry {dry}")
    check(dry["payload"]["meta"]["source"] == "cloud_cursor_workshop", dry["payload"]["meta"])

    from learner.db import Store, reset_store

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TEACHING_DB"] = path
    reset_store()
    try:
        store = Store(path)
        with patch("learner.db.get_store", return_value=store):
            out = ingest.import_one(item, judge, apply=True, require_judge_accept=True)
        check(out.get("ok") is True, f"apply {out}")
        check(out.get("judge_applied") is True, out)
        check(out.get("quality_tier") == "pass", out)
        row = store.get_item(int(out["item_id"]))
        check(row is not None, "row exists")
        check((row.get("meta") or {}).get("source") == "cloud_cursor_workshop", row.get("meta"))
        check(row.get("quality_tier") == "pass", row.get("quality_tier"))
    finally:
        os.environ.pop("TEACHING_DB", None)
        reset_store()
        try:
            os.remove(path)
        except OSError:
            pass


def test_ingest_main_rejects_review_file() -> None:
    ingest = _load("ingest_incoming", WS / "ingest_incoming.py")
    val = _load("validate_incoming", WS / "validate_incoming.py")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ws-review.json"
        import json
        p.write_text(
            json.dumps(_math_item(subject="review", id="ws-rev"), ensure_ascii=False),
            encoding="utf-8",
        )
        syll = _syll()
        with patch.object(ingest, "load_syllabus", side_effect=lambda *_a, **_k: {"kps": {}}), \
             patch.object(ingest, "index_syllabus", return_value=syll), \
             patch.object(ingest, "check_item", side_effect=val.check_item):
            rc = ingest.main([td])
        check(rc == 1, f"review file should fail ingest rc={rc}")


def main() -> int:
    test_validate_rejects_review_and_comm_without_atom()
    test_ingest_dry_run_and_apply_pass()
    test_ingest_main_rejects_review_file()
    print("fails", _fails)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
