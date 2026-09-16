# -*- coding: utf-8 -*-
"""One-shot acceptance of PR #16 zhou_comm.db against the 12-day spec."""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "atom_books" / "zhou_comm.db"
SYL = ROOT / "data" / "syllabus_comm.json"
OCR = Path(r"D:\cc\ai-systems\knowledge-system\data\ocr_pages") / "通信原理（周炯槃）"
PACK = ROOT / "data" / "atom_books" / "zhou_pack"
EXPECTED_BLOB = "9cf58b66b04a9f9703bbbae3ea123ecc4f633888"
EXPECTED_SIZE = 6279168
HANDOFF_CH = {2: 38, 3: 36, 4: 38, 5: 40, 6: 73, 7: 42, 8: 23, 9: 84, 10: 22, 11: 15}
EMPTY_PAGES = {145, 227, 306, 324, 379, 393, 416}
REQUIRED_TERMS = ["奈奎斯特", "ISI", "匹配滤波", "香农", "眼图", "滚降", "维特比"]

fails: list[str] = []
warns: list[str] = []


def ok(msg: str) -> None:
    print("[PASS]", msg)


def fail(msg: str) -> None:
    fails.append(msg)
    print("[FAIL]", msg)


def warn(msg: str) -> None:
    warns.append(msg)
    print("[WARN]", msg)


def git_hash_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main() -> int:
    if not DB.is_file():
        fail("db missing")
        return 2
    size = DB.stat().st_size
    (ok if size == EXPECTED_SIZE else fail)(f"db size={size}")
    blob = git_hash_blob(DB)
    (ok if blob == EXPECTED_BLOB else fail)(f"git blob={blob}")

    tmpdir = Path(tempfile.mkdtemp(prefix="zhou_accept_"))
    tmpdb = tmpdir / "zhou_comm.db"
    shutil.copy2(DB, tmpdb)
    conn = sqlite3.connect(str(tmpdb))
    conn.row_factory = sqlite3.Row
    chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
    (ok if chk == "ok" else fail)(f"integrity={chk}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    (ok if not fk else fail)(f"fk_check {len(fk)}")

    fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paragraphs_fts'"
    ).fetchone()
    (ok if fts else fail)("paragraphs_fts missing")

    meta = dict(conn.execute("SELECT key, value FROM meta"))
    print("meta", meta)
    expect = {
        "book": "通信原理（周炯槃）",
        "edition": "4",
        "page_offset": "13",
        "schema_rev": "1",
    }
    for k, v in expect.items():
        (ok if meta.get(k) == v else fail)(f"meta {k}={meta.get(k)!r}")

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    need = {"meta", "pages", "paragraphs", "atoms", "atom_spans", "atom_l3", "terms"}
    missing = need - tables
    (ok if not missing else fail)(f"tables missing={missing or 'none'}")

    counts = {
        "pages": conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
        "paragraphs": conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0],
        "atoms": conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0],
        "atom_spans": conn.execute("SELECT COUNT(*) FROM atom_spans").fetchone()[0],
        "atom_l3": conn.execute("SELECT COUNT(*) FROM atom_l3").fetchone()[0],
        "terms": conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0],
    }
    print("counts", counts)
    (ok if counts["pages"] == 433 else fail)(f"pages={counts['pages']}")
    (ok if counts["paragraphs"] == 6532 else fail)(f"paragraphs={counts['paragraphs']}")
    (ok if counts["atoms"] == 411 else fail)(f"atoms={counts['atoms']}")
    (ok if counts["atom_spans"] == 1464 else fail)(f"atom_spans={counts['atom_spans']}")
    (ok if counts["atom_l3"] == 582 else fail)(f"atom_l3={counts['atom_l3']}")
    (ok if counts["terms"] == 1368 else fail)(f"terms={counts['terms']}")

    empty = {
        r[0]
        for r in conn.execute(
            """
            SELECT p.print_page FROM pages p
            LEFT JOIN paragraphs g ON g.print_page=p.print_page
            GROUP BY p.print_page HAVING COUNT(g.id)=0
            """
        )
    }
    print("empty pages", sorted(empty))
    (ok if empty == EMPTY_PAGES else fail)(f"empty pages {sorted(empty)}")

    no_core = conn.execute(
        """
        SELECT a.id FROM atoms a
        LEFT JOIN atom_spans s ON a.id=s.atom_id AND s.role='core'
        WHERE s.atom_id IS NULL
        """
    ).fetchall()
    (ok if not no_core else fail)(
        f"atoms without core span: {len(no_core)} {[r[0] for r in no_core[:5]]}"
    )

    empty_stmt = conn.execute(
        "SELECT id FROM atoms WHERE statement IS NULL OR trim(statement)=''"
    ).fetchall()
    (ok if not empty_stmt else fail)(f"empty statement {len(empty_stmt)}")

    uuidish = [
        r[0]
        for r in conn.execute("SELECT id FROM atoms")
        if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", r[0], re.I)
    ]
    (ok if not uuidish else fail)(f"uuid atom ids {uuidish[:5]}")

    underscore = [
        r[0]
        for r in conn.execute("SELECT id FROM atoms")
        if "_" in r[0]
    ]
    if underscore:
        warn(f"atom ids with underscore (style, still stable): {underscore}")
    bad_id = [
        r[0]
        for r in conn.execute("SELECT id FROM atoms")
        if not re.match(r"^zhou\.ch\d+\.[a-z0-9_.]+$", r[0])
    ]
    (ok if not bad_id else fail)(f"bad atom ids {len(bad_id)} {bad_id[:5]}")

    huge = conn.execute(
        """
        SELECT atom_id, COUNT(*) n FROM atom_spans
        WHERE role='core' GROUP BY atom_id HAVING n>6
        """
    ).fetchall()
    (ok if not huge else fail)(f"core spans >6: {len(huge)} {[dict(r) for r in huge[:5]]}")

    para_ids = conn.execute("SELECT id, print_page, seq FROM paragraphs").fetchall()
    bad_para = []
    for r in para_ids:
        pg, seq = int(r["print_page"]), int(r["seq"])
        if pg >= 0:
            expect_id = f"zhou.p{pg:03d}.s{seq:02d}"
        else:
            expect_id = f"zhou.pm{abs(pg):02d}.s{seq:02d}"
        if r["id"] != expect_id:
            bad_para.append((r["id"], expect_id))
            if len(bad_para) >= 5:
                break
    (ok if not bad_para else fail)(f"paragraph id scheme {bad_para[:3]}")

    syl = json.loads(SYL.read_text(encoding="utf-8"))
    l3_ids = set()
    for m in (syl.get("kps") or {}).values():
        if isinstance(m, dict):
            for l3 in m.get("l3") or []:
                if isinstance(l3, dict) and l3.get("id"):
                    l3_ids.add(l3["id"])
    mapped = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT l3_id FROM atom_l3 WHERE confidence>=0.6"
        )
    }
    invented = sorted(mapped - l3_ids)
    (ok if not invented else fail)(f"invented l3 {invented[:8]}")
    gaps = sorted(l3_ids - mapped)
    cov = len(mapped & l3_ids) / max(1, len(l3_ids))
    print("L3 coverage", round(cov, 4), "mapped", len(mapped & l3_ids), "of", len(l3_ids), "gaps", gaps)
    (ok if cov >= 0.8 else fail)(f"coverage {cov:.4f}")
    (ok if gaps == ["comm.analog_mod.nbfm"] else fail)(f"gaps {gaps}")

    rows = conn.execute(
        """
        SELECT a.id, a.chapter, a.created_day, MIN(p.print_page) AS pg
        FROM atoms a
        JOIN atom_spans s ON s.atom_id=a.id AND s.role='core'
        JOIN paragraphs p ON p.id=s.paragraph_id
        GROUP BY a.id
        ORDER BY a.chapter, pg, a.id
        """
    ).fetchall()
    chs = [int(r["chapter"]) for r in rows]
    (ok if chs == sorted(chs) else fail)("book order chapter monotonic")
    ch_counts = {c: chs.count(c) for c in sorted(set(chs))}
    print("chapter counts", ch_counts)
    (ok if ch_counts == HANDOFF_CH else fail)(f"chapter counts vs HANDOFF {ch_counts}")
    extra_ch = set(ch_counts) - set(range(2, 12))
    (ok if not extra_ch else fail)(f"atoms outside Ch2-11: {extra_ch}")
    print("first atoms", [(r["id"], r["chapter"], r["pg"], r["created_day"]) for r in rows[:5]])

    off = int(meta["page_offset"])
    mismatch = conn.execute(
        "SELECT COUNT(*) FROM pages WHERE pdf_page - print_page != ?",
        (off,),
    ).fetchone()[0]
    (ok if mismatch == 0 else fail)(f"page_offset mismatches {mismatch}")

    for term in REQUIRED_TERMS:
        n = conn.execute(
            "SELECT COUNT(*) FROM terms WHERE term = ? OR term LIKE ?",
            (term, f"%{term}%"),
        ).fetchone()[0]
        (ok if n > 0 else fail)(f"term {term!r} hits={n}")

    fan = conn.execute(
        "SELECT COUNT(*) FROM atoms WHERE id LIKE 'fan.%' OR statement LIKE '%樊昌信%'"
    ).fetchone()[0]
    (ok if fan == 0 else fail)(f"fan contamination atoms={fan}")

    if not OCR.is_dir():
        fail(f"OCR dir missing {OCR}")
    else:
        rng = random.Random(20260910)
        sample = rng.sample(list(rows), 20)
        hit = 0
        miss = []
        details = []
        for a in sample:
            spans = conn.execute(
                """
                SELECT p.print_page, pg.pdf_page, p.text
                FROM atom_spans s
                JOIN paragraphs p ON p.id=s.paragraph_id
                JOIN pages pg ON pg.print_page=p.print_page
                WHERE s.atom_id=? AND s.role='core'
                ORDER BY p.print_page, p.seq LIMIT 1
                """,
                (a["id"],),
            ).fetchone()
            pdf = int(spans["pdf_page"])
            f = OCR / f"page_{pdf:03d}.md"
            if not f.is_file():
                miss.append((a["id"], f"missing {f.name}"))
                continue
            body = re.sub(r"\s+", "", f.read_text(encoding="utf-8", errors="replace"))
            snippet = re.sub(r"\s+", "", (spans["text"] or "").strip()[:48])
            key = snippet[:16]
            details.append(
                {
                    "atom": a["id"],
                    "print": int(spans["print_page"]),
                    "pdf": pdf,
                    "file": f.name,
                    "key": key,
                    "hit": bool(key and key in body),
                }
            )
            if key and key in body:
                hit += 1
            else:
                miss.append((a["id"], f"print={spans['print_page']} pdf={pdf} {snippet[:24]!r}"))
        print("ocr sample", json.dumps(details, ensure_ascii=False))
        print("ocr hit", hit, "/", len(sample))
        if miss:
            print("ocr miss", miss)
        (ok if hit >= 16 else fail)(f"ocr locator {hit}/{len(sample)}")

    conn.close()
    shutil.rmtree(tmpdir, ignore_errors=True)

    print("FAILS", len(fails))
    for m in fails:
        print(" -", m)
    print("WARNS", len(warns))
    for m in warns:
        print(" -", m)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
