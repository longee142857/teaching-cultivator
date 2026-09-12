# -*- coding: utf-8 -*-
"""推进模式：atom 硬过滤 / walk 关闭 / 预留槽 / 过关闸。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _fails += 1


def _make_zhou(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE pages (
          print_page INTEGER PRIMARY KEY, pdf_page INTEGER NOT NULL,
          chapter TEXT, text TEXT NOT NULL, checksum TEXT NOT NULL, n_chars INTEGER NOT NULL
        );
        CREATE TABLE paragraphs (
          id TEXT PRIMARY KEY, print_page INTEGER NOT NULL REFERENCES pages(print_page),
          seq INTEGER NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
          text TEXT NOT NULL, kind TEXT NOT NULL, UNIQUE (print_page, seq)
        );
        CREATE TABLE atoms (
          id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
          statement TEXT NOT NULL, chapter INTEGER NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]', created_day INTEGER NOT NULL
        );
        CREATE TABLE atom_spans (
          atom_id TEXT NOT NULL REFERENCES atoms(id),
          paragraph_id TEXT NOT NULL REFERENCES paragraphs(id),
          role TEXT NOT NULL, PRIMARY KEY (atom_id, paragraph_id)
        );
        CREATE TABLE atom_l3 (
          atom_id TEXT NOT NULL REFERENCES atoms(id),
          l3_id TEXT NOT NULL, confidence REAL NOT NULL,
          PRIMARY KEY (atom_id, l3_id)
        );
        """
    )
    conn.execute(
        "INSERT INTO meta(key,value) VALUES ('book','通信原理（周炯槃）'),"
        "('edition','4'),('schema_rev','1')"
    )
    conn.execute(
        "INSERT INTO pages VALUES (10,23,'2','傅里叶', 'a', 4)"
    )
    conn.execute(
        "INSERT INTO pages VALUES (40,53,'3','信道', 'b', 4)"
    )
    conn.execute(
        "INSERT INTO pages VALUES (200,53,'8','晚灌', 'c', 4)"
    )
    conn.execute(
        "INSERT INTO paragraphs VALUES ('zhou.p010.s01',10,1,0,10,'傅里叶级数定义','body')"
    )
    conn.execute(
        "INSERT INTO paragraphs VALUES ('zhou.p010.s02',10,2,0,10,'未对齐段落','body')"
    )
    conn.execute(
        "INSERT INTO paragraphs VALUES ('zhou.p040.s01',40,1,0,10,'信道容量陈述','body')"
    )
    conn.execute(
        "INSERT INTO paragraphs VALUES ('zhou.p200.s01',200,1,0,10,'后章','body')"
    )
    # created_day 故意让后章先灌
    conn.execute(
        "INSERT INTO atoms VALUES ('zhou.ch8.late','definition','晚灌原子',"
        "'后章陈述',8,'[]',1)"
    )
    conn.execute(
        "INSERT INTO atoms VALUES ('zhou.ch2.fourier','definition','傅里叶级数',"
        "'周期信号可展成傅里叶级数',2,'[]',9)"
    )
    conn.execute(
        "INSERT INTO atoms VALUES ('zhou.ch2.unmapped','definition','无映射',"
        "'对不上考纲',2,'[]',9)"
    )
    conn.execute(
        "INSERT INTO atoms VALUES ('zhou.ch3.capacity','definition','信道容量',"
        "'香农容量公式',3,'[]',9)"
    )
    conn.execute(
        "INSERT INTO atom_spans VALUES ('zhou.ch2.fourier','zhou.p010.s01','core')"
    )
    conn.execute(
        "INSERT INTO atom_spans VALUES ('zhou.ch2.unmapped','zhou.p010.s02','core')"
    )
    conn.execute(
        "INSERT INTO atom_spans VALUES ('zhou.ch3.capacity','zhou.p040.s01','core')"
    )
    conn.execute(
        "INSERT INTO atom_spans VALUES ('zhou.ch8.late','zhou.p200.s01','core')"
    )
    conn.execute(
        "INSERT INTO atom_l3 VALUES ('zhou.ch2.fourier','comm.sig_rand.fourier.series',0.9)"
    )
    conn.execute(
        "INSERT INTO atom_l3 VALUES ('zhou.ch3.capacity','comm.sig_rand.energy_psd',0.85)"
    )
    conn.execute(
        "INSERT INTO atom_l3 VALUES ('zhou.ch8.late','comm.sig_rand.lti',0.8)"
    )
    conn.commit()
    conn.close()


def _bind(store, zhou_path: str, accepted: bool = True):
    from learner.db import reset_store

    os.environ["ZHOU_COMM_DB"] = zhou_path
    os.environ["ZHOU_COMM_ACCEPTED"] = "1" if accepted else "0"
    os.environ["ADVANCE_FILL_ON_ENABLE"] = "0"
    os.environ["OWNER_STAFF_ID"] = "owner_adv"
    os.environ["TEACHING_DB"] = store.path
    reset_store()


def test_accept_missing() -> None:
    from learner.atom_book import schema_ok, book_accepted

    os.environ.pop("ZHOU_COMM_DB", None)
    os.environ["ZHOU_COMM_ACCEPTED"] = "0"
    with tempfile.TemporaryDirectory() as td:
        os.environ["ZHOU_COMM_DB"] = os.path.join(td, "nope.db")
        ok, why = schema_ok()
        check(ok is False, "missing db schema_ok false")
        check("missing" in why, f"missing reason {why}")
        check(book_accepted() is False, "not accepted without env")


def test_book_order_and_unmapped() -> None:
    from learner.atom_book import list_atoms_in_book_order
    from learner.advance import skip_unmapped, set_learning_mode
    from learner.db import Store
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=True)
        ids = [r["id"] for r in list_atoms_in_book_order()]
        check(ids[0] == "zhou.ch2.fourier", f"book order starts ch2 not late {ids}")
        check("zhou.ch8.late" == ids[-1], f"late chapter last {ids}")
        with bind_learner("owner_adv", binding="schedule"):
            r = set_learning_mode("comm", "advance", "zhou_comm")
            check(r.get("ok") is True, f"set advance ok {r}")
            mapped = skip_unmapped("owner_adv", "zhou_comm", "zhou.ch2.unmapped")
            check(mapped.get("atom_id") == "zhou.ch3.capacity", f"skip unmapped → next mapped {mapped}")
            check("zhou.ch2.unmapped" in (mapped.get("skipped") or []), "unmapped recorded skip")


def test_mode_refused_without_accept() -> None:
    from learner.advance import set_learning_mode
    from learner.db import Store
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=False)
        with bind_learner("owner_adv", binding="schedule"):
            r = set_learning_mode("comm", "advance", "zhou_comm")
            check(r.get("ok") is False, f"advance refused {r}")
            check(r.get("error") == "book_not_accepted", f"error {r}")


def test_atom_hard_filter_no_walk() -> None:
    from learner.db import Store
    from learner.item_bank import pick_for_push, pick_for_push_walk

    with tempfile.TemporaryDirectory() as td:
        from learner.db import reset_store

        dbp = os.path.join(td, "t.db")
        os.environ["TEACHING_DB"] = dbp
        reset_store()
        store = Store(dbp)
        crc = store.insert_bank_item(
            subject="comm", question="CRC题", answer="1",
            kp="循环码与CRC", l3_id="comm.coding.crc", status="ready",
        )
        atom_q = store.insert_bank_item(
            subject="comm", question="傅里叶原子题", answer="2",
            kp="确定信号与频谱分析", l3_id="comm.sig_rand.fourier.series",
            status="ready", atom_id="zhou.ch2.fourier", book_id="zhou_comm",
        )
        store.apply_judge_verdict(crc, verdict="pass", reasons=["t"], confidence=1.0)
        store.apply_judge_verdict(atom_q, verdict="pass", reasons=["t"], confidence=1.0)

        hit = pick_for_push("comm", kp="确定信号与频谱分析", atom_id="zhou.ch2.fourier")
        check(hit is not None and int(hit["id"]) == atom_q, f"atom pick {hit}")
        walk = pick_for_push_walk(
            "comm", kp="确定信号与频谱分析", atom_id="zhou.ch2.fourier"
        )
        check(walk is not None and int(walk["id"]) == atom_q, "walk disabled still atom")
        miss = pick_for_push("comm", kp="循环码与CRC", atom_id="zhou.ch2.missing")
        check(miss is None, "no L1/L2 fallback when atom set")
        free = pick_for_push_walk("comm", kp="不存在的KP")
        check(free is not None and int(free["id"]) in (crc, atom_q), "free walk still works")


def test_quota_full_reserved_and_rag() -> None:
    from learner.db import Store
    from learner.advance import set_learning_mode, reserved_comm_spec
    from learner.rag_retrieve import rag_retrieve
    from learner.context import bind_learner
    from cultivate_bank import _pregenerate_one_inner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=True)
        for i in range(6):
            iid = store.insert_bank_item(
                subject="comm", question=f"配额题{i}", answer="x",
                kp="循环码与CRC", status="ready",
            )
            store.apply_judge_verdict(iid, verdict="pass", reasons=["t"], confidence=1.0)
        with bind_learner("owner_adv", binding="schedule"):
            set_learning_mode("comm", "advance", "zhou_comm")
            spec = reserved_comm_spec("owner_adv")
            check(spec is not None, f"reserved despite quota {spec}")
            check((spec or {}).get("atom_id") == "zhou.ch2.fourier", f"pin first mapped {spec}")
            check((spec or {}).get("l3_id") == "comm.sig_rand.fourier.series", "pin l3 not pick_l3")

            os.environ["BANK_QUOTA_COMM"] = "6"
            with patch("cultivate_bank._author_spec", return_value={"ok": True, "item_id": 99}) as auth:
                out = _pregenerate_one_inner("comm")
                check(out.get("ok") is True, f"reserved pregen {out}")
                check(auth.called, "quota_full did not skip reserved")
                called_spec = auth.call_args[0][1]
                check(called_spec.get("atom_id") == "zhou.ch2.fourier", "author got atom spec")

        rag = rag_retrieve("comm", "comm.sig_rand.fourier.series", atom_id="zhou.ch2.fourier", book_id="zhou_comm")
        check(rag.backend == "zhou_sqlite", f"backend {rag.backend}")
        check(rag.ok is True and rag.hit_count >= 1, f"spans ok {rag}")
        check(all("樊" not in (s.get("source") or "") for s in rag.snippets), "no fan chroma")


def test_grade_gate_partial_and_advance() -> None:
    from learner.db import Store
    from learner.advance import apply_atom_grade, get_cursor, ensure_cursor
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=True)
        with bind_learner("owner_adv", binding="schedule"):
            ensure_cursor("owner_adv", "zhou_comm")
            r1 = apply_atom_grade(
                learner_id="owner_adv", book_id="zhou_comm",
                atom_id="zhou.ch2.fourier", slot="comm",
                verdict="partial", status="applied", credit=0.5,
            )
            check(r1.get("advanced") is False, "partial does not pass")
            cur = get_cursor("owner_adv", "zhou_comm")
            check((cur or {}).get("atom_id") == "zhou.ch2.fourier", "cursor stay on partial")

            apply_atom_grade(
                learner_id="owner_adv", book_id="zhou_comm",
                atom_id="zhou.ch2.fourier", slot="review",
                verdict="correct", status="applied", credit=None,
            )
            cur = get_cursor("owner_adv", "zhou_comm")
            check((cur or {}).get("atom_id") == "zhou.ch2.fourier", "review correct ignored")

            apply_atom_grade(
                learner_id="owner_adv", book_id="zhou_comm",
                atom_id="zhou.ch2.fourier", slot="comm",
                verdict="correct", status="applied", credit=None,
            )
            apply_atom_grade(
                learner_id="owner_adv", book_id="zhou_comm",
                atom_id="zhou.ch2.fourier", slot="comm",
                verdict="correct", status="applied", credit=None,
            )
            cur = get_cursor("owner_adv", "zhou_comm")
            check((cur or {}).get("atom_id") == "zhou.ch2.unmapped" or
                  (cur or {}).get("atom_id") == "zhou.ch3.capacity",
                  f"advanced after 2 correct {cur}")


def test_three_way_missing_atom_no_cursor() -> None:
    from grade import _maybe_advance_grade
    from learner.db import Store
    from learner.advance import ensure_cursor, get_cursor
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=True)
        with bind_learner("owner_adv", binding="schedule"):
            ensure_cursor("owner_adv", "zhou_comm")
            _maybe_advance_grade(
                question="无 atom 旧题",
                verdict="correct",
                status="applied",
                credit=None,
            )
            cur = get_cursor("owner_adv", "zhou_comm")
            check((cur or {}).get("atom_id") == "zhou.ch2.fourier", f"missing atom_id does not move cursor {cur}")


def test_book_db_path_prefers_git_layout() -> None:
    from learner.atom_book import book_db_path, BOOK_ZHOU

    with tempfile.TemporaryDirectory() as td:
        git_p = os.path.join(td, "zhou_comm", "zhou_comm.db")
        old_p = os.path.join(td, "atom_books", "zhou_comm.db")
        os.makedirs(os.path.dirname(git_p), exist_ok=True)
        os.makedirs(os.path.dirname(old_p), exist_ok=True)
        open(git_p, "wb").write(b"git")
        open(old_p, "wb").write(b"old")
        os.environ.pop("ZHOU_COMM_DB", None)
        with patch("learner.atom_book._data_dir", return_value=td):
            p = book_db_path(BOOK_ZHOU)
        check(p == git_p, f"prefer git layout {p}")
        os.environ["ZHOU_COMM_DB"] = old_p
        with patch("learner.atom_book._data_dir", return_value=td):
            p2 = book_db_path(BOOK_ZHOU)
        check(p2 == old_p, f"env override {p2}")
        os.environ.pop("ZHOU_COMM_DB", None)


def test_ensure_reserved_fills_pass_for_pick() -> None:
    from learner.db import Store
    from learner.advance import set_learning_mode, ensure_reserved_comm_item
    from learner.item_bank import pick_for_push
    from learner.context import bind_learner

    with tempfile.TemporaryDirectory() as td:
        zhou = os.path.join(td, "zhou_comm.db")
        _make_zhou(zhou)
        store = Store(os.path.join(td, "t.db"))
        _bind(store, zhou, accepted=True)
        for i in range(6):
            iid = store.insert_bank_item(
                subject="comm", question=f"旧题{i}", answer="x",
                kp="循环码与CRC", status="ready",
            )
            store.apply_judge_verdict(iid, verdict="pass", reasons=["t"], confidence=1.0)

        def fake_author(subject, spec):
            iid = store.insert_bank_item(
                subject="comm",
                question="傅里叶预留",
                answer="级数",
                kp=spec.get("kp") or "确定信号与频谱分析",
                l3_id=spec.get("l3_id") or "",
                status="ready",
                atom_id=spec["atom_id"],
                book_id=spec.get("book_id") or "zhou_comm",
            )
            store.apply_judge_verdict(iid, verdict="pass", reasons=["t"], confidence=1.0)
            return {"ok": True, "item_id": iid}

        with bind_learner("owner_adv", binding="schedule"):
            set_learning_mode("comm", "advance", "zhou_comm")
            empty = pick_for_push("comm", kp="确定信号与频谱分析", atom_id="zhou.ch2.fourier")
            check(empty is None, f"old bank has no atom_id {empty}")
            with patch("cultivate_bank._author_spec", side_effect=fake_author):
                fill = ensure_reserved_comm_item("owner_adv", judge=False)
            check(fill.get("ok") is True, f"ensure ok {fill}")
            hit = pick_for_push("comm", kp="确定信号与频谱分析", atom_id="zhou.ch2.fourier")
            check(hit is not None and "傅里叶预留" in (hit.get("question") or ""), f"pick reserved {hit}")


def main() -> int:
    test_accept_missing()
    test_book_order_and_unmapped()
    test_mode_refused_without_accept()
    test_atom_hard_filter_no_walk()
    test_quota_full_reserved_and_rag()
    test_grade_gate_partial_and_advance()
    test_three_way_missing_atom_no_cursor()
    test_book_db_path_prefers_git_layout()
    test_ensure_reserved_fills_pass_for_pick()
    print("fails", _fails)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
