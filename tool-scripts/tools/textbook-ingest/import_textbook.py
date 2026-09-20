#!/usr/bin/env python3
"""Import textbook_example JSON into teaching.db.

Thin wrapper around bank-workshop/import_incoming.py. Defaults --incoming
to data/textbook_ingest/puheping_math_contest_v2 (recursive).

Isolated ops path: does **not** touch cultivate.py / cultivate_bank.py /
learner/item_bank.py / learner/db.py / prompts / web.

meta.source=textbook_example → insert ready + apply_judge_verdict(pass)
with reasons=['textbook_example']. cloud_cursor_workshop is NOT auto-passed
(workshop still needs *.judge.json decision=accept).

Default is dry-run. Pass --apply to write teaching.db. Never writes the
repo teaching.db unless --apply --db is given. Catalog JSON is not moved.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

IMPORT_INCOMING = (
    Path(__file__).resolve().parents[1] / "bank-workshop" / "import_incoming.py"
)


def _load_importer():
    if not IMPORT_INCOMING.is_file():
        raise FileNotFoundError(f"import_incoming.py missing: {IMPORT_INCOMING}")
    spec = importlib.util.spec_from_file_location(
        "bank_workshop_import_incoming", IMPORT_INCOMING
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {IMPORT_INCOMING}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        mod = _load_importer()
    except Exception as e:
        print(f"failed to load import_incoming.py: {e}", file=sys.stderr)
        return 2
    if "--incoming" not in argv:
        argv = ["--incoming", str(mod.DEFAULT_TEXTBOOK_INCOMING), *argv]
    return int(mod.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
