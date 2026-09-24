#!/usr/bin/env python3
"""Import accepted bank_workshop / textbook_ingest JSON into teaching.db.

Isolated ops path: does **not** touch cultivate.py / cultivate_bank.py /
learner/item_bank.py / learner/db.py / prompts / web.

Writes via the same store API as cultivate_bank:

    store.insert_bank_item(..., status="ready")  # quality_tier starts pending
    store.apply_judge_verdict(iid, verdict="pass", ...)

Workshop (`meta.source=cloud_cursor_workshop`) still requires companion
`*.judge.json` with `decision==accept` and reasons=`workshop_accept`.
Textbook examples (`meta.source=textbook_example`) do **not** need a
judge file: original worked solutions, pass with reasons=`textbook_example`.
Do **not** auto-pass workshop items.

`--incoming` may point at `data/textbook_ingest/puheping_math_contest_v2`
(recursive). Default is dry-run (no DB writes, no file moves). Pass
`--apply` to commit. Never prints secrets. Never scans rejected/.
Never touches learners / attempts / pushes / BKT / sessions / .env.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[3]
VALIDATE_PATH = ROOT / "data" / "bank_workshop" / "validate_incoming.py"
DEFAULT_INCOMING = ROOT / "data" / "bank_workshop" / "incoming"
DEFAULT_IMPORTED = ROOT / "data" / "bank_workshop" / "imported"
DEFAULT_TEXTBOOK_INCOMING = (
    ROOT / "data" / "textbook_ingest" / "puheping_math_contest_v2"
)
LOCAL_SYLL_COMM = ROOT / "data" / "syllabus_comm.json"
LOCAL_SYLL_MATH = ROOT / "data" / "syllabus_math.json"

ALLOWED_SUBJECTS = {"math", "comm"}
ALLOWED_DIFFICULTY = {"", "hit"}
SOURCE_WORKSHOP = "cloud_cursor_workshop"
SOURCE_TEXTBOOK = "textbook_example"
REF_SOURCE = SOURCE_WORKSHOP  # workshop default; textbook uses textbook:{book_id}
DEFAULT_TEXTBOOK_BOOK_ID = "puheping_math_contest_v2"
TEXTBOOK_REF_SOURCE = f"textbook:{DEFAULT_TEXTBOOK_BOOK_ID}"
TEXTBOOK_ID_PREFIX = "tx-pu-"
SKIP_ITEM_NAMES = {"schema.example.json"}
TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STEP_SPLIT = re.compile(r"(?=(?:^|[；;.。]\s*)\d+[\)）.、]\s*)")


def _ensure_root_on_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _load_validate():
    if not VALIDATE_PATH.is_file():
        raise FileNotFoundError(f"validate_incoming.py missing: {VALIDATE_PATH}")
    spec = importlib.util.spec_from_file_location(
        "bank_workshop_validate_incoming", VALIDATE_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {VALIDATE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_payload_validator() -> Callable[..., str]:
    _ensure_root_on_path()
    from learner.item_bank import validate_bank_payload

    return validate_bank_payload


def _resolve(path: str | Path, *, default_root: Path = ROOT) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = default_root / p
    return p


def default_db_path() -> Path:
    env = (os.environ.get("TEACHING_DB") or "").strip()
    if env:
        return Path(env)
    return ROOT / "data" / "teaching.db"


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def iter_item_paths(incoming: Path) -> list[Path]:
    files: list[Path] = []
    if not incoming.exists():
        return files
    for p in incoming.rglob("*.json"):
        if p.name.endswith(".judge.json"):
            continue
        if p.name in SKIP_ITEM_NAMES or p.name.endswith(".example.json"):
            continue
        if "rejected" in p.parts:
            continue
        files.append(p)
    return sorted(files)


def item_meta(item: dict | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    meta = item.get("meta")
    return dict(meta) if isinstance(meta, dict) else {}


def item_source(item: dict | None) -> str:
    return str(item_meta(item).get("source") or "").strip()


def is_textbook_item(item: dict | None) -> bool:
    return item_source(item) == SOURCE_TEXTBOOK


def textbook_book_id(item: dict) -> str:
    meta = item_meta(item)
    book = str(item.get("book_id") or meta.get("book_id") or "").strip()
    return book or DEFAULT_TEXTBOOK_BOOK_ID


def textbook_ref_source(item: dict) -> str:
    """Keep JSON ref_source if present; else textbook:{book_id}."""
    meta = item_meta(item)
    for raw in (item.get("ref_source"), meta.get("ref_source")):
        text = str(raw or "").strip()
        if text:
            return text
    return f"textbook:{textbook_book_id(item)}" or TEXTBOOK_REF_SOURCE


def judge_path_for(item_path: Path) -> Path:
    return item_path.with_name(item_path.stem + ".judge.json")


def batch_day(item_path: Path, incoming_root: Path) -> str:
    try:
        rel = item_path.parent.relative_to(incoming_root)
        if rel.parts and DAY_RE.fullmatch(rel.parts[0]):
            return rel.parts[0]
    except ValueError:
        pass
    if DAY_RE.fullmatch(item_path.parent.name):
        return item_path.parent.name
    return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")


def difficulty_of(item: dict) -> tuple[str, str]:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    raw = meta.get("difficulty")
    if raw in (None, ""):
        raw = item.get("difficulty")
    if raw in (None, ""):
        return "", ""
    text = str(raw).strip()
    if text.lower() == "basic":
        return "", "difficulty_forbidden_basic"
    if text not in ALLOWED_DIFFICULTY:
        return "", f"difficulty_not_hit_or_empty={text!r}"
    return text, ""


def _steps_from_text(text: str) -> list[dict[str, str]]:
    blob = (text or "").strip()
    if not blob:
        return []
    chunks = [c.strip().lstrip("；;").strip() for c in STEP_SPLIT.split(blob)]
    steps: list[dict[str, str]] = []
    for chunk in chunks:
        if not chunk:
            continue
        steps.append({"id": f"s{len(steps) + 1}", "text": chunk})
    if not steps:
        steps = [{"id": "s1", "text": blob}]
    return steps


def as_solution(raw: Any, *, answer: str, techniques: list) -> dict:
    """Normalize to {steps, final_answer, techniques_used}. No placeholder steps."""
    if isinstance(raw, dict):
        sol = dict(raw)
        if not (sol.get("steps") or []):
            fallback = str(sol.get("text") or raw.get("workshop_text") or "").strip()
            sol["steps"] = _steps_from_text(fallback)
        sol["final_answer"] = sol.get("final_answer") or (answer or "")[:500]
        sol["techniques_used"] = list(sol.get("techniques_used") or techniques or [])
        return {
            "steps": list(sol.get("steps") or []),
            "final_answer": sol.get("final_answer") or "",
            "techniques_used": list(sol.get("techniques_used") or []),
        }
    steps = _steps_from_text(str(raw or ""))
    return {
        "steps": steps,
        "final_answer": (answer or "")[:500],
        "techniques_used": list(techniques or []),
    }


def as_cdps(raw: Any, techniques: list) -> tuple[list[dict], str]:
    """Require a CDP object list. Do not invent dummy prompts.

    If workshop already stored objects, keep them as-is (missing technique →
    validate_bank_payload fails). Integer count is not a payload — fail rather
    than fabricate cultivate_bank-style placeholder CDPs.
    """
    if isinstance(raw, list):
        out = []
        for c in raw:
            if isinstance(c, dict):
                out.append(dict(c))
        return out, ""
    return [], "cdps_not_object_list"


def item_to_bank_kwargs(item: dict) -> tuple[Optional[dict[str, Any]], str]:
    """Map incoming JSON → insert_bank_item kwargs. kp←l2, l3_id←l3_id."""
    subject = str(item.get("subject") or "").strip()
    if subject not in ALLOWED_SUBJECTS:
        return None, f"subject_not_math_comm={subject!r}"
    l2 = str(item.get("l2") or "").strip()
    l3_id = str(item.get("l3_id") or "").strip()
    if not l2:
        return None, "missing_l2"
    if not l3_id:
        return None, "missing_l3_id"
    techniques = [str(t).strip() for t in (item.get("techniques") or []) if str(t).strip()]
    answer = str(item.get("answer") or "")
    diff, diff_err = difficulty_of(item)
    if diff_err:
        return None, diff_err
    cdps, cdp_err = as_cdps(item.get("cdps"), techniques)
    if cdp_err:
        return None, cdp_err
    textbook = is_textbook_item(item)
    src = item_source(item)
    if textbook:
        wid = str(item.get("id") or "").strip()
        book = textbook_book_id(item)
        if book == DEFAULT_TEXTBOOK_BOOK_ID and not wid.startswith(TEXTBOOK_ID_PREFIX):
            return None, f"textbook_id_prefix_expected_{TEXTBOOK_ID_PREFIX}"
        atom_id = str(item.get("atom_id") or "").strip()
        # math may omit atom_id; comm still needs a Zhou atom (validate_incoming).
        meta: dict[str, Any] = item_meta(item)
        meta["source"] = SOURCE_TEXTBOOK
        meta["book_id"] = book
        if wid:
            meta.setdefault("textbook_id", wid)
        ref_source = textbook_ref_source(item)
        kwargs = {
            "subject": subject,
            "question": str(item.get("question") or ""),
            "answer": answer,
            "difficulty": diff,
            "kp": l2,
            "l3_id": l3_id,
            "item_form": str(item.get("item_form") or ""),
            "ability_goal": str(item.get("ability_goal") or ""),
            "ref_source": ref_source,
            "techniques": techniques,
            "solution": as_solution(item.get("solution"), answer=answer, techniques=techniques),
            "cdps": cdps,
            "meta": meta,
            "status": "ready",
            "atom_id": atom_id,
            "book_id": book if subject == "math" else str(item.get("book_id") or "").strip(),
        }
        return kwargs, ""
    if src and src != SOURCE_WORKSHOP:
        return None, f"unsupported_meta.source={src!r}"
    meta = item_meta(item)
    meta["source"] = SOURCE_WORKSHOP
    meta["workshop_id"] = item.get("id") or ""
    kwargs = {
        "subject": subject,
        "question": str(item.get("question") or ""),
        "answer": answer,
        "difficulty": diff,
        "kp": l2,
        "l3_id": l3_id,
        "item_form": str(item.get("item_form") or ""),
        "ability_goal": str(item.get("ability_goal") or ""),
        "ref_source": REF_SOURCE,
        "techniques": techniques,
        "solution": as_solution(item.get("solution"), answer=answer, techniques=techniques),
        "cdps": cdps,
        "meta": meta,
        "status": "ready",
        "atom_id": str(item.get("atom_id") or "").strip(),
        "book_id": str(item.get("book_id") or "").strip(),
    }
    return kwargs, ""


def workshop_to_bank_kwargs(item: dict) -> tuple[Optional[dict[str, Any]], str]:
    """Alias: workshop + textbook mapping share item_to_bank_kwargs."""
    return item_to_bank_kwargs(item)


def load_syllabus_index(validate, comm: str, math: str) -> dict[str, dict]:
    syll: dict[str, dict] = {}
    syll.update(validate.index_syllabus(validate.load_syllabus(comm)))
    syll.update(validate.index_syllabus(validate.load_syllabus(math)))
    return syll


def _syllabus_arg(cli: Optional[str], local: Path, url_fallback: str) -> str:
    if cli:
        p = _resolve(cli)
        return str(p) if p.exists() else cli
    if local.is_file():
        return str(local)
    return url_fallback


def open_store(db_path: Path):
    _ensure_root_on_path()
    from learner.db import get_store

    return get_store(str(db_path))


def move_pair(
    item_path: Path,
    judge_file: Path,
    *,
    imported_root: Path,
    day: str,
) -> Path:
    dest_dir = imported_root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_item = dest_dir / item_path.name
    dest_judge = dest_dir / judge_file.name
    if dest_item.exists() or dest_judge.exists():
        raise FileExistsError(f"already in imported: {dest_item.name}")
    shutil.move(str(item_path), str(dest_item))
    if judge_file.exists():
        shutil.move(str(judge_file), str(dest_judge))
    return dest_item


def item_for_workshop_check(item: dict) -> dict:
    """validate_incoming treats cdps as an int count; bank payload uses objects."""
    copy = dict(item)
    cdps = item.get("cdps")
    if isinstance(cdps, list):
        copy["cdps"] = len(cdps)
    return copy


def classify_skip(item: dict | None, judge: dict | None, judge_file: Path) -> str:
    if item is None:
        return "bad_item_json"
    subj = str(item.get("subject") or "").strip()
    if subj not in ALLOWED_SUBJECTS:
        return f"subject_not_math_comm={subj!r}"
    if is_textbook_item(item):
        # Textbook originals: no companion judge file. Workshop is NOT auto-pass.
        return ""
    if not judge_file.exists() or judge is None:
        return "no_judge"
    dec = judge.get("decision")
    if dec != "accept":
        return f"judge.decision={dec!r}"
    return ""


def process(
    *,
    incoming: Path,
    imported_root: Path,
    db_path: Path,
    apply: bool,
    move: bool,
    limit: int | None,
    syll_comm: str,
    syll_math: str,
) -> int:
    if not incoming.exists():
        print(f"incoming dir missing: {incoming}", file=sys.stderr)
        return 2

    try:
        validate = _load_validate()
    except Exception as e:
        print(f"failed to load validate_incoming.py: {e}", file=sys.stderr)
        return 2

    try:
        payload_check = load_payload_validator()
    except Exception as e:
        print(f"failed to import validate_bank_payload: {e}", file=sys.stderr)
        return 2

    try:
        syll = load_syllabus_index(validate, syll_comm, syll_math)
    except Exception as e:
        print(f"failed to load syllabus: {e}", file=sys.stderr)
        return 2

    paths = iter_item_paths(incoming)
    if limit is not None:
        paths = paths[: max(0, int(limit))]

    mode = "apply" if apply else "dry-run"
    if apply and not db_path.is_file():
        print(f"teaching.db not found: {db_path}", file=sys.stderr)
        print(
            "Hint: pass --db PATH or set TEACHING_DB; this script will not create a new production DB.",
            file=sys.stderr,
        )
        return 2

    print(f"mode={mode} incoming={incoming} db={db_path}")
    n_examples = sum(
        1
        for p in incoming.rglob("*.json")
        if p.name in SKIP_ITEM_NAMES or p.name.endswith(".example.json")
    )
    if n_examples:
        print(f"note: skipped {n_examples} catalog example JSON (not imported)")
    if not db_path.is_file():
        print(f"note: teaching.db not found at {db_path} (--apply will fail)")

    store = None
    if apply:
        try:
            store = open_store(db_path)
        except Exception as e:
            print(f"failed to open store: {e}", file=sys.stderr)
            return 2

    imported = skipped = failed = 0
    for path in paths:
        jpath = judge_path_for(path)
        item = None
        judge = None
        try:
            item = load_json(path)
        except Exception as e:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)} bad_json:{e}")
            continue
        if jpath.exists():
            try:
                judge = load_json(jpath)
            except Exception as e:
                failed += 1
                print(f"FAIL {path.relative_to(incoming)} bad_judge_json:{e}")
                continue

        skip_reason = classify_skip(item, judge, jpath)
        if skip_reason:
            skipped += 1
            print(f"SKIP {path.relative_to(incoming)} {skip_reason}")
            continue

        textbook = is_textbook_item(item)
        allowed_sources = {SOURCE_TEXTBOOK} if textbook else {SOURCE_WORKSHOP}
        errs = validate.check_item(
            item_for_workshop_check(item),
            syll,
            not textbook,
            judge,
            allowed_sources=allowed_sources,
        )
        if errs:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)}")
            for e in errs[:8]:
                print(f"  - {e}")
            continue

        kwargs, map_err = item_to_bank_kwargs(item)
        if map_err or not kwargs:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)} map:{map_err}")
            continue

        payload_err = payload_check(
            question=kwargs["question"],
            techniques=kwargs["techniques"],
            solution=kwargs["solution"],
            cdps=kwargs["cdps"],
        )
        if payload_err:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)} payload:{payload_err}")
            continue

        src_id = kwargs["meta"].get("textbook_id") or kwargs["meta"].get("workshop_id")
        if not apply:
            imported += 1
            print(
                f"DRY  {path.relative_to(incoming)} "
                f"id={src_id} source={kwargs['meta'].get('source')} "
                f"ref_source={kwargs['ref_source']} "
                f"subject={kwargs['subject']} kp={kwargs['kp']} l3={kwargs['l3_id']}"
            )
            continue

        assert store is not None
        item_id = None
        if textbook:
            reasons = ["textbook_example"]
            details = {
                "source": SOURCE_TEXTBOOK,
                "ref_source": kwargs["ref_source"],
                "quality_basis": kwargs["meta"].get("quality_basis"),
                "textbook_id": src_id,
            }
        else:
            reasons = ["workshop_accept"]
            details = judge or {}
        try:
            item_id = store.insert_bank_item(**kwargs)
            store.apply_judge_verdict(
                item_id,
                verdict="pass",
                reasons=reasons,
                confidence=1.0,
                details=details,
            )
        except Exception as e:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)} insert:{e}")
            continue

        # Catalog JSON stays in textbook_ingest/; only workshop incoming is moved.
        do_move = move and not textbook
        if do_move:
            try:
                dest = move_pair(
                    path,
                    jpath,
                    imported_root=imported_root,
                    day=batch_day(path, incoming),
                )
                loc = dest.relative_to(imported_root)
            except Exception as e:
                failed += 1
                print(
                    f"FAIL {path.relative_to(incoming)} "
                    f"item_id={item_id} moved=0 move:{e}"
                )
                continue
        else:
            loc = path.relative_to(incoming)
        imported += 1
        print(
            f"OK   {path.name} item_id={item_id} "
            f"source={kwargs['meta'].get('source')} "
            f"subject={kwargs['subject']} kp={kwargs['kp']} -> {loc}"
        )

    print(f"imported={imported} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Import accepted bank_workshop incoming JSON, or textbook_example "
            "JSON from data/textbook_ingest/, into teaching.db"
        )
    )
    ap.add_argument(
        "--db",
        default="",
        help="teaching.db path (default: $TEACHING_DB or data/teaching.db)",
    )
    ap.add_argument(
        "--incoming",
        default=str(DEFAULT_INCOMING),
        help=(
            "incoming root to scan recursively "
            "(default: data/bank_workshop/incoming; "
            "textbook: data/textbook_ingest/puheping_math_contest_v2)"
        ),
    )
    ap.add_argument(
        "--imported",
        default=str(DEFAULT_IMPORTED),
        help="move destination root (default: data/bank_workshop/imported)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="scan+validate only (default). No DB writes, no moves.",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help=(
            "insert_bank_item + apply_judge_verdict(pass) and move workshop "
            "incoming on success. textbook_example: pass without judge file; "
            "cloud_cursor_workshop is NOT auto-passed"
        ),
    )
    ap.add_argument(
        "--no-move",
        action="store_true",
        help="with --apply, write DB but leave JSON in incoming/",
    )
    ap.add_argument("--limit", type=int, default=None, help="process at most N item JSON files")
    ap.add_argument("--syllabus-comm", default="", help="override comm syllabus path/URL")
    ap.add_argument("--syllabus-math", default="", help="override math syllabus path/URL")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    apply = bool(args.apply)
    incoming = _resolve(args.incoming)
    imported_root = _resolve(args.imported)
    db_path = _resolve(args.db) if args.db else default_db_path()

    url_comm = url_math = ""
    try:
        validate_mod = _load_validate()
        url_comm = getattr(validate_mod, "DEFAULT_COMM", "")
        url_math = getattr(validate_mod, "DEFAULT_MATH", "")
    except Exception:
        pass

    syll_comm = _syllabus_arg(args.syllabus_comm or None, LOCAL_SYLL_COMM, url_comm)
    syll_math = _syllabus_arg(args.syllabus_math or None, LOCAL_SYLL_MATH, url_math)

    return process(
        incoming=incoming,
        imported_root=imported_root,
        db_path=db_path,
        apply=apply,
        move=not args.no_move,
        limit=args.limit,
        syll_comm=syll_comm,
        syll_math=syll_math,
    )


if __name__ == "__main__":
    raise SystemExit(main())
