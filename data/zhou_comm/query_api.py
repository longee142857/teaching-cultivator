#!/usr/bin/env python3
"""Read-only SQLite query API for zhou_comm.db (Day 11).

Hot path: PK / terms / FTS5 only — no embed, no LLM, no network.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

DEFAULT_DB = Path(__file__).resolve().parent / "zhou_comm.db"


def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    # URI read-only; immutable=0 so WAL companion files still work if present
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


class ZhouCommQuery:
    """Reusable read-only query handle (open DB once, reuse for bench)."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.conn = _connect(self.db_path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ZhouCommQuery":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ get
    def get(
        self,
        print_page: int,
        paras: Optional[Sequence[int]] = None,
    ) -> list[dict[str, Any]]:
        """Fetch paragraph texts + paragraph_ids for a print page.

        paras: page-local seq numbers (1-based). If None/empty → all paras on page.
        Returns list of {paragraph_id, print_page, seq, text, kind, char_start, char_end}.
        """
        if paras:
            seqs = [int(s) for s in paras]
            placeholders = ",".join("?" * len(seqs))
            sql = f"""
                SELECT id AS paragraph_id, print_page, seq, text, kind,
                       char_start, char_end
                FROM paragraphs
                WHERE print_page = ? AND seq IN ({placeholders})
                ORDER BY seq
            """
            cur = self.conn.execute(sql, (int(print_page), *seqs))
        else:
            cur = self.conn.execute(
                """
                SELECT id AS paragraph_id, print_page, seq, text, kind,
                       char_start, char_end
                FROM paragraphs
                WHERE print_page = ?
                ORDER BY seq
                """,
                (int(print_page),),
            )
        return _rows_to_dicts(cur.fetchall())

    # --------------------------------------------------------------- lookup
    def lookup(self, term: str) -> list[dict[str, Any]]:
        """Resolve term → atoms + spans (print_page + paragraph_id).

        1) Exact match on terms.term (primary / indexed).
        2) If empty, FTS5 trigram match on paragraphs → atoms via atom_spans.
        """
        term = (term or "").strip()
        if not term:
            return []

        atom_ids = self._atom_ids_by_term(term)
        via = "terms"
        if not atom_ids:
            atom_ids = self._atom_ids_by_fts(term)
            via = "fts5"
        if not atom_ids:
            return []

        return self._atoms_with_spans(atom_ids, extra={"matched_via": via, "query": term})

    def _atom_ids_by_term(self, term: str) -> list[str]:
        cur = self.conn.execute(
            "SELECT DISTINCT atom_id FROM terms WHERE term = ? ORDER BY atom_id",
            (term,),
        )
        return [r[0] for r in cur.fetchall()]

    def _atom_ids_by_fts(self, term: str, limit: int = 40) -> list[str]:
        # FTS5 trigram: quote phrase; escape double quotes inside
        q = '"' + term.replace('"', '""') + '"'
        cur = self.conn.execute(
            """
            SELECT DISTINCT s.atom_id
            FROM paragraphs_fts f
            JOIN paragraphs p ON p.rowid = f.rowid
            JOIN atom_spans s ON s.paragraph_id = p.id
            WHERE paragraphs_fts MATCH ?
            ORDER BY s.atom_id
            LIMIT ?
            """,
            (q, limit),
        )
        return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------------------ l3
    def l3(self, l3_id: str, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        """All atoms mapped to l3_id + locators (print_page + paragraph_id)."""
        l3_id = (l3_id or "").strip()
        if not l3_id:
            return []
        cur = self.conn.execute(
            """
            SELECT atom_id, confidence
            FROM atom_l3
            WHERE l3_id = ? AND confidence >= ?
            ORDER BY confidence DESC, atom_id
            """,
            (l3_id, float(min_confidence)),
        )
        rows = cur.fetchall()
        if not rows:
            return []
        conf_map = {r["atom_id"]: r["confidence"] for r in rows}
        atom_ids = list(conf_map.keys())
        results = self._atoms_with_spans(
            atom_ids, extra={"l3_id": l3_id, "confidence_by_atom": conf_map}
        )
        # attach per-atom confidence
        for item in results:
            item["confidence"] = conf_map.get(item["atom_id"])
            item["l3_id"] = l3_id
        return results

    # ------------------------------------------------------------- helpers
    def _atoms_with_spans(
        self,
        atom_ids: Sequence[str],
        extra: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        if not atom_ids:
            return []
        placeholders = ",".join("?" * len(atom_ids))
        atoms = _rows_to_dicts(
            self.conn.execute(
                f"""
                SELECT id AS atom_id, type, name, statement, chapter,
                       aliases_json, created_day
                FROM atoms
                WHERE id IN ({placeholders})
                """,
                tuple(atom_ids),
            ).fetchall()
        )
        by_id = {a["atom_id"]: a for a in atoms}
        spans = _rows_to_dicts(
            self.conn.execute(
                f"""
                SELECT s.atom_id, s.paragraph_id, s.role,
                       p.print_page, p.seq
                FROM atom_spans s
                JOIN paragraphs p ON p.id = s.paragraph_id
                WHERE s.atom_id IN ({placeholders})
                ORDER BY s.atom_id, p.print_page, p.seq
                """,
                tuple(atom_ids),
            ).fetchall()
        )
        spans_by: dict[str, list[dict[str, Any]]] = {aid: [] for aid in atom_ids}
        for sp in spans:
            spans_by.setdefault(sp["atom_id"], []).append(
                {
                    "paragraph_id": sp["paragraph_id"],
                    "print_page": sp["print_page"],
                    "seq": sp["seq"],
                    "role": sp["role"],
                }
            )

        # preserve atom_ids order
        out: list[dict[str, Any]] = []
        for aid in atom_ids:
            a = by_id.get(aid)
            if not a:
                continue
            locators = spans_by.get(aid, [])
            item: dict[str, Any] = {
                "atom_id": a["atom_id"],
                "type": a["type"],
                "name": a["name"],
                "statement": a["statement"],
                "chapter": a["chapter"],
                "spans": locators,
                "print_page": sorted({s["print_page"] for s in locators}),
                "paragraph_ids": [s["paragraph_id"] for s in locators],
            }
            if extra:
                if "matched_via" in extra:
                    item["matched_via"] = extra["matched_via"]
                if "query" in extra:
                    item["query"] = extra["query"]
            out.append(item)
        return out


# ---------------------------------------------------------------------------
# Module-level helpers (importable)
# ---------------------------------------------------------------------------
_default_q: Optional[ZhouCommQuery] = None


def _default() -> ZhouCommQuery:
    global _default_q
    if _default_q is None:
        _default_q = ZhouCommQuery()
    return _default_q


def get(print_page: int, paras: Optional[Sequence[int]] = None) -> list[dict[str, Any]]:
    return _default().get(print_page, paras)


def lookup(term: str) -> list[dict[str, Any]]:
    return _default().lookup(term)


def l3(l3_id: str, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    return _default().l3(l3_id, min_confidence=min_confidence)


# ---------------------------------------------------------------------------
# Bench + QA
# ---------------------------------------------------------------------------
def _p99(samples_ms: list[float]) -> float:
    if not samples_ms:
        return 0.0
    ordered = sorted(samples_ms)
    # nearest-rank p99
    k = max(0, min(len(ordered) - 1, int(round(0.99 * len(ordered))) - 1))
    # use ceil index for p99 of n=50 → index 49 (0-based) = max; better: numpy-less
    idx = max(0, min(len(ordered) - 1, (99 * (len(ordered) - 1) + 99) // 100))
    return ordered[idx]


def _percentile(samples_ms: list[float], p: float) -> float:
    if not samples_ms:
        return 0.0
    ordered = sorted(samples_ms)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def run_bench(
    db_path: Union[str, Path] = DEFAULT_DB,
    repeats: int = 50,
    out_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Open DB once; repeat each op `repeats` times; write bench.json."""
    out_path = out_path or Path(db_path).resolve().parent / "bench.json"

    with ZhouCommQuery(db_path) as q:
        # warm / pick representative args from live data
        page_row = q.conn.execute(
            "SELECT print_page FROM paragraphs "
            "WHERE print_page >= 1 "
            "GROUP BY print_page HAVING COUNT(*) >= 4 "
            "ORDER BY print_page LIMIT 1"
        ).fetchone()
        print_page = int(page_row[0]) if page_row else 50
        seqs = [
            r[0]
            for r in q.conn.execute(
                "SELECT seq FROM paragraphs WHERE print_page=? ORDER BY seq LIMIT 4",
                (print_page,),
            ).fetchall()
        ]
        term_row = q.conn.execute(
            "SELECT term FROM terms WHERE term IN "
            "('奈奎斯特','匹配滤波','香农公式','眼图','ISI') "
            "LIMIT 1"
        ).fetchone()
        if not term_row:
            term_row = q.conn.execute("SELECT term FROM terms LIMIT 1").fetchone()
        term = term_row[0] if term_row else "奈奎斯特"
        l3_row = q.conn.execute(
            "SELECT l3_id FROM atom_l3 WHERE confidence >= 0.6 "
            "GROUP BY l3_id HAVING COUNT(*) >= 1 ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        l3_id = l3_row[0] if l3_row else "comm.baseband.isi.nyquist"

        # warmup once each (not counted)
        q.get(print_page, seqs)
        q.lookup(term)
        q.l3(l3_id)

        def timed(fn, n=repeats):
            samples = []
            for _ in range(n):
                t0 = time.perf_counter()
                fn()
                samples.append((time.perf_counter() - t0) * 1000.0)
            return samples

        get_ms = timed(lambda: q.get(print_page, seqs))
        lookup_ms = timed(lambda: q.lookup(term))
        l3_ms = timed(lambda: q.l3(l3_id))

        # sanity: results carry locators
        get_res = q.get(print_page, seqs)
        lookup_res = q.lookup(term)
        l3_res = q.l3(l3_id)

        def summarize(name, samples, target_ms, ok_extra=True):
            p50 = _percentile(samples, 50)
            p99 = _percentile(samples, 99)
            return {
                "op": name,
                "n": len(samples),
                "p50_ms": round(p50, 4),
                "p99_ms": round(p99, 4),
                "mean_ms": round(statistics.mean(samples), 4),
                "max_ms": round(max(samples), 4),
                "target_p99_ms": target_ms,
                "pass": bool(p99 < target_ms and ok_extra),
            }

        get_ok = all("paragraph_id" in r and "print_page" in r for r in get_res)
        lookup_ok = all(
            r.get("paragraph_ids") and r.get("print_page") is not None for r in lookup_res
        ) and len(lookup_res) > 0
        l3_ok = all(
            r.get("paragraph_ids") and r.get("print_page") is not None for r in l3_res
        ) and len(l3_res) > 0

        report = {
            "db": str(Path(db_path).resolve()),
            "repeats": repeats,
            "opened_once": True,
            "args": {
                "get": {"print_page": print_page, "paras": seqs},
                "lookup": {"term": term},
                "l3": {"l3_id": l3_id},
            },
            "result_counts": {
                "get": len(get_res),
                "lookup": len(lookup_res),
                "l3": len(l3_res),
            },
            "locator_ok": {"get": get_ok, "lookup": lookup_ok, "l3": l3_ok},
            "ops": [
                summarize("get", get_ms, 3.0, get_ok),
                summarize("lookup", lookup_ms, 10.0, lookup_ok),
                summarize("l3", l3_ms, 10.0, l3_ok),
            ],
        }
        report["all_pass"] = all(op["pass"] for op in report["ops"])

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def sample_l3_qa(
    db_path: Union[str, Path] = DEFAULT_DB,
    n: int = 20,
    seed: int = 20260911,
    out_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Sample n L3 ids with mappings; verify each returns print_page + paragraph_id."""
    import random

    out_path = out_path or Path(db_path).resolve().parent / "qa" / "sample-day-11.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with ZhouCommQuery(db_path) as q:
        ids = [
            r[0]
            for r in q.conn.execute(
                """
                SELECT DISTINCT l3_id FROM atom_l3
                WHERE confidence >= 0.6
                ORDER BY l3_id
                """
            ).fetchall()
        ]
        rng = random.Random(seed)
        if len(ids) > n:
            chosen = sorted(rng.sample(ids, n))
        else:
            chosen = ids

        samples = []
        all_pass = True
        for lid in chosen:
            atoms = q.l3(lid, min_confidence=0.6)
            fail_reasons: list[str] = []
            if not atoms:
                fail_reasons.append("no_atoms")
            for a in atoms:
                if not a.get("paragraph_ids"):
                    fail_reasons.append(f"{a['atom_id']}:missing_paragraph_ids")
                if not a.get("print_page"):
                    fail_reasons.append(f"{a['atom_id']}:missing_print_page")
                for sp in a.get("spans") or []:
                    if sp.get("print_page") is None or not sp.get("paragraph_id"):
                        fail_reasons.append(f"{a['atom_id']}:span_missing_locator")
            ok = len(fail_reasons) == 0 and len(atoms) > 0
            if not ok:
                all_pass = False
            samples.append(
                {
                    "l3_id": lid,
                    "n_atoms": len(atoms),
                    "atoms": [
                        {
                            "atom_id": a["atom_id"],
                            "name": a["name"],
                            "confidence": a.get("confidence"),
                            "print_page": a["print_page"],
                            "paragraph_ids": a["paragraph_ids"],
                        }
                        for a in atoms
                    ],
                    "pass": ok,
                    "fail_reasons": fail_reasons,
                }
            )

    report = {
        "day": 11,
        "seed": seed,
        "n": len(samples),
        "all_pass": all_pass,
        "samples": samples,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _demo(q: ZhouCommQuery) -> None:
    print("=== get(50, paras=[3,4]) ===")
    for r in q.get(50, [3, 4]):
        print(f"  {r['paragraph_id']} p{r['print_page']}.s{r['seq']}: {r['text'][:60]!r}...")
    print("=== lookup('奈奎斯特') ===")
    for a in q.lookup("奈奎斯特")[:3]:
        print(
            f"  {a['atom_id']} pages={a['print_page']} paras={a['paragraph_ids'][:4]} via={a.get('matched_via')}"
        )
    print("=== l3 (top mapped) ===")
    row = q.conn.execute(
        "SELECT l3_id FROM atom_l3 WHERE confidence>=0.6 "
        "GROUP BY l3_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()
    lid = row[0]
    for a in q.l3(lid)[:3]:
        print(f"  [{lid}] {a['atom_id']} conf={a['confidence']} pages={a['print_page']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="zhou_comm.db read-only query API (Day 11)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to zhou_comm.db")
    sub = ap.add_subparsers(dest="cmd")

    p_get = sub.add_parser("get", help="get(print_page, paras)")
    p_get.add_argument("print_page", type=int)
    p_get.add_argument("--paras", type=int, nargs="*", default=None)

    p_lookup = sub.add_parser("lookup", help="lookup(term)")
    p_lookup.add_argument("term")

    p_l3 = sub.add_parser("l3", help="l3(l3_id)")
    p_l3.add_argument("l3_id")
    p_l3.add_argument("--min-confidence", type=float, default=0.0)

    p_bench = sub.add_parser("bench", help="run latency bench → bench.json")
    p_bench.add_argument("--repeats", type=int, default=50)

    p_qa = sub.add_parser("qa", help="sample 20 L3 → qa/sample-day-11.json")
    p_qa.add_argument("--n", type=int, default=20)
    p_qa.add_argument("--seed", type=int, default=20260911)

    sub.add_parser("demo", help="print small demo")

    args = ap.parse_args(argv)

    if args.cmd is None or args.cmd == "demo":
        with ZhouCommQuery(args.db) as q:
            _demo(q)
        return 0

    if args.cmd == "bench":
        report = run_bench(args.db, repeats=args.repeats)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_pass"] else 1

    if args.cmd == "qa":
        report = sample_l3_qa(args.db, n=args.n, seed=args.seed)
        print(json.dumps({"n": report["n"], "all_pass": report["all_pass"]}, ensure_ascii=False))
        return 0 if report["all_pass"] else 1

    with ZhouCommQuery(args.db) as q:
        if args.cmd == "get":
            print(json.dumps(q.get(args.print_page, args.paras), ensure_ascii=False, indent=2))
        elif args.cmd == "lookup":
            print(json.dumps(q.lookup(args.term), ensure_ascii=False, indent=2))
        elif args.cmd == "l3":
            print(
                json.dumps(
                    q.l3(args.l3_id, min_confidence=args.min_confidence),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
