#!/usr/bin/env python3
"""Import accepted bank_workshop incoming JSON into teaching.db.

Isolated ops path: does **not** touch cultivate.py / cultivate_bank.py /
learner/item_bank.py / learner/db.py / prompts / web.

Writes via the same store API as cultivate_bank:

    store.insert_bank_item(...)
    store.apply_judge_verdict(item_id, verdict="pass", ...)

Default is dry-run (no DB writes, no file moves). Pass --apply to commit.
Never prints secrets. Never scans rejected/.
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
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
VALIDATE_PATH = ROOT / "data" / "bank_workshop" / "validate_incoming.py"
DEFAULT_INCOMING = ROOT / "data" / "bank_workshop" / "incoming"
DEFAULT_IMPORTED = ROOT / "data" / "bank_workshop" / "imported"
LOCAL_SYLL_COMM = ROOT / "data" / "syllabus_comm.json"
LOCAL_SYLL_MATH = ROOT / "data" / "syllabus_math.json"

ALLOWED_SUBJECTS = {"math", "comm"}
REF_SOURCE = "cloud_cursor_workshop"
TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STEP_SPLIT = re.compile(r"(?=(?:^|[；;.。]\s*)\d+[\)）.、]\s*)")


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
        if "rejected" in p.parts:
            continue
        files.append(p)
    return sorted(files)


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


def _difficulty(item: dict) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    raw = meta.get("difficulty")
    if raw in (None, ""):
        raw = item.get("difficulty")
    if raw in (None, ""):
        return ""
    text = str(raw).strip()
    if text.lower() == "basic":
        return ""
    return text


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
    """Workshop solution is a string; teaching.db stores a steps dict."""
    if isinstance(raw, dict):
        sol = dict(raw)
        if not (sol.get("steps") or []):
            fallback = str(sol.get("text") or answer or "").strip()
            sol["steps"] = _steps_from_text(fallback) or [
                {"id": "s1", "text": fallback or "见题干推导"}
            ]
        sol.setdefault("final_answer", (answer or "")[:500])
        sol.setdefault("techniques_used", list(techniques or []))
        return sol
    steps = _steps_from_text(str(raw or ""))
    if not steps:
        steps = [{"id": "s1", "text": (answer or "见题干推导")[:2000]}]
    return {
        "steps": steps,
        "final_answer": (answer or "")[:500],
        "techniques_used": list(techniques or []),
    }


def as_cdps(raw: Any, techniques: list) -> list[dict]:
    """Workshop cdps is an integer count; teaching.db stores a CDP list."""
    if isinstance(raw, list) and len(raw) >= 2:
        out = []
        for i, c in enumerate(raw, 1):
            if isinstance(c, dict):
                row = dict(c)
                row.setdefault("id", f"cdp{i}")
                row.setdefault("technique", (techniques[:1] or ["core_method"])[0])
                out.append(row)
        if len(out) >= 2:
            return out
    n = 2
    try:
        n = max(2, int(raw))
    except (TypeError, ValueError):
        n = 2
    techs = [str(t).strip() for t in (techniques or []) if str(t).strip()] or [
        "core_method"
    ]
    out = []
    for i in range(n):
        tech = techs[i] if i < len(techs) else techs[0]
        out.append(
            {
                "id": f"cdp{i + 1}",
                "prompt": (
                    "识别本题关键方法/定理" if i == 0 else "执行关键步骤并得到结论"
                ),
                "expected": tech if i == 0 else "正确推导",
                "technique": tech,
                "depends_on": [] if i == 0 else [f"cdp{i}"],
            }
        )
    return out


def workshop_to_bank_kwargs(item: dict) -> dict[str, Any]:
    subject = str(item.get("subject") or "").strip()
    l3_id = str(item.get("l3_id") or "").strip()
    techniques = list(item.get("techniques") or [])
    answer = str(item.get("answer") or "")
    meta = {}
    if isinstance(item.get("meta"), dict):
        meta.update(item["meta"])
    meta["workshop_id"] = item.get("id") or ""
    meta["source"] = REF_SOURCE
    atom_id = str(item.get("atom_id") or "").strip()
    book_id = str(item.get("book_id") or "").strip()
    return {
        "subject": subject,
        "question": str(item.get("question") or ""),
        "answer": answer,
        "difficulty": _difficulty(item),
        "kp": l3_id,
        "l3_id": l3_id,
        "item_form": str(item.get("item_form") or ""),
        "ability_goal": str(item.get("ability_goal") or ""),
        "ref_source": REF_SOURCE,
        "techniques": techniques,
        "solution": as_solution(item.get("solution"), answer=answer, techniques=techniques),
        "cdps": as_cdps(item.get("cdps"), techniques),
        "meta": meta,
        "status": "ready",
        "atom_id": atom_id,
        "book_id": book_id,
    }


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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
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


def classify_skip(item: dict | None, judge: dict | None, judge_file: Path) -> str:
    if not judge_file.exists() or judge is None:
        return "no_judge"
    dec = judge.get("decision")
    if dec != "accept":
        return f"judge.decision={dec!r}"
    if item is None:
        return "bad_item_json"
    subj = str(item.get("subject") or "").strip()
    if subj not in ALLOWED_SUBJECTS:
        return f"subject_not_math_comm={subj!r}"
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

        errs = validate.check_item(item, syll, True, judge)
        if errs:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)}")
            for e in errs[:8]:
                print(f"  - {e}")
            continue

        kwargs = workshop_to_bank_kwargs(item)
        if not apply:
            imported += 1
            print(
                f"DRY  {path.relative_to(incoming)} "
                f"id={kwargs['meta'].get('workshop_id')} "
                f"subject={kwargs['subject']} l3={kwargs['l3_id']}"
            )
            continue

        assert store is not None
        try:
            item_id = store.insert_bank_item(**kwargs)
            store.apply_judge_verdict(
                item_id,
                verdict="pass",
                reasons=["bank_workshop_accept"],
                details=judge or {},
            )
            if move:
                dest = move_pair(
                    path,
                    jpath,
                    imported_root=imported_root,
                    day=batch_day(path, incoming),
                )
                loc = dest.relative_to(imported_root)
            else:
                loc = path.relative_to(incoming)
            imported += 1
            print(
                f"OK   {path.name} item_id={item_id} "
                f"subject={kwargs['subject']} -> {loc}"
            )
        except Exception as e:
            failed += 1
            print(f"FAIL {path.relative_to(incoming)} insert:{e}")

    print(f"imported={imported} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Import accepted bank_workshop incoming JSON into teaching.db"
    )
    ap.add_argument(
        "--db",
        default="",
        help="teaching.db path (default: $TEACHING_DB or data/teaching.db)",
    )
    ap.add_argument(
        "--incoming",
        default=str(DEFAULT_INCOMING),
        help="incoming root to scan recursively (default: data/bank_workshop/incoming)",
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
        help="actually insert_bank_item + apply_judge_verdict(pass) and move files",
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

    validate_mod = None
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
