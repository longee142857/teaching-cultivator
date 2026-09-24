#!/usr/bin/env python3
"""Hard-check workshop incoming JSON (+ optional *.judge.json) against syllabi."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_COMM = "https://raw.githubusercontent.com/longee142857/teaching-cultivator/master/data/syllabus_comm.json"
DEFAULT_MATH = "https://raw.githubusercontent.com/longee142857/teaching-cultivator/master/data/syllabus_math.json"
ALLOWED_FORMS = {"blank", "proof_outline"}
ALLOWED_GOALS = {"compute", "construct"}
# Keywords only. Do NOT casefold \(A-D\): math args like pf(c) / f(x) are not options.
_MCQ_KEYWORD_RE = re.compile(r"(?i)(选择题|单选|多选|选项[ABCD]|recognize)")
# Inline A. … B. (or A) … B)) pair — letters stay case-sensitive.
_MCQ_AB_PAIR_RE = re.compile(r"\bA[\.．、\)]\s*.+\bB[\.．、\)]", re.DOTALL)
# Option at line start: (A) / （A） / A. / A、
_MCQ_OPTION_LINE_RE = re.compile(r"(?m)^\s*(?:\([A-D]\)|（[A-D]）|[A-D][\.．、])")
# Standalone uppercase (A)–(D); not after an identifier so f(C) / pf(c) do not count.
_MCQ_OPTION_TOKEN_RE = re.compile(r"(?<![A-Za-z\\])(?:\([A-D]\)|（[A-D]）)")


def question_looks_like_mcq(question: str) -> bool:
    """True only for real choice stems, not a lone math argument (c)/(x).

    A single ``(A)`` / ``(c)`` is not enough. Need a keyword, an A…B pair,
    ≥2 option-start lines, or ≥2 standalone uppercase ``(A)``–``(D)`` tokens.
    """
    q = str(question or "")
    if not q.strip():
        return False
    if _MCQ_KEYWORD_RE.search(q):
        return True
    if _MCQ_AB_PAIR_RE.search(q):
        return True
    if len(_MCQ_OPTION_LINE_RE.findall(q)) >= 2:
        return True
    if len(_MCQ_OPTION_TOKEN_RE.findall(q)) >= 2:
        return True
    return False


ROOT = Path(__file__).resolve().parents[2]


def load_syllabus(path_or_url: str) -> dict:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": "bank-workshop-validate"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(path_or_url).read_text(encoding="utf-8"))


def index_syllabus(data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for l2, kp in (data.get("kps") or {}).items():
        for l3 in kp.get("l3") or []:
            out[l3["id"]] = {"l2": l2, "l3_name": l3.get("name"), "subject": data.get("subject")}
    return out


def load_item(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_solution(sol: Any) -> list[str]:
    """Bank payload: solution must be {steps>=2, final_answer, techniques_used}."""
    errs: list[str] = []
    if isinstance(sol, str):
        errs.append("solution must be object, not string")
        return errs
    if not isinstance(sol, dict):
        errs.append(f"solution must be object, got {type(sol).__name__}")
        return errs
    steps = sol.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        n = len(steps) if isinstance(steps, list) else type(steps).__name__
        errs.append(f"solution.steps must be list >= 2, got {n!r}")
    else:
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or not s.get("id") or not str(s.get("text") or "").strip():
                errs.append(f"solution.steps[{i}] missing id/text")
    if not str(sol.get("final_answer") or "").strip():
        errs.append("solution.final_answer missing")
    return errs


def _check_cdps(cdps: Any) -> list[str]:
    """Object list is required for import; int count is a legacy workshop shorthand.

    import_incoming.item_for_workshop_check maps a CDP list to len(cdps) before
    calling this, so integers (>=2) remain accepted here. Direct validate of
    incoming JSON should see a list of objects.
    """
    errs: list[str] = []
    if isinstance(cdps, list):
        if len(cdps) < 2:
            errs.append(f"cdps must be object list >= 2, got {len(cdps)}")
            return errs
        for i, c in enumerate(cdps):
            if not isinstance(c, dict):
                errs.append(f"cdps[{i}] must be object, got {type(c).__name__}")
                continue
            cid = c.get("id") or f"#{i}"
            if not c.get("id"):
                errs.append(f"cdp[{cid}] missing id")
            if not str(c.get("technique") or "").strip():
                errs.append(f"cdp[{cid}] missing technique")
            if not str(c.get("prompt") or "").strip():
                errs.append(f"cdp[{cid}] missing prompt")
            if not str(c.get("expected") or "").strip():
                errs.append(f"cdp[{cid}] missing expected")
        return errs
    if isinstance(cdps, int) or (isinstance(cdps, str) and str(cdps).strip().lstrip("-").isdigit()):
        try:
            n = int(cdps)
        except (TypeError, ValueError):
            n = -1
        if n < 2:
            errs.append(f"cdps must be >= 2, got {cdps!r}")
        return errs
    errs.append(f"cdps must be object list (not integer count) or int-like >=2, got {cdps!r}")
    return errs


def payload_err(item: dict) -> str:
    """Local replica of learner.item_bank.validate_bank_payload (+ ≥2 steps).

    Used when teaching.db / import dry-run is unavailable. Empty string = pass.
    """
    if not str(item.get("question") or "").strip():
        return "empty_question"
    techs = item.get("techniques") or []
    if not techs:
        return "no_techniques"
    sol = item.get("solution")
    if not isinstance(sol, dict):
        return "solution_not_object"
    steps = sol.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return "no_solution_steps"
    if len(steps) < 2:
        return "solution_steps_lt_2"
    cdps = item.get("cdps")
    if not isinstance(cdps, list) or len(cdps) < 2:
        return "cdps_lt_2"
    for c in cdps:
        if not isinstance(c, dict) or not c.get("id"):
            return "cdp_missing_id"
        if not c.get("technique"):
            return "cdp_missing_technique"
    return ""


def check_item(
    item: dict,
    syll: dict[str, dict],
    require_judge_accept: bool,
    judge: dict | None,
    *,
    allowed_sources: set[str] | frozenset[str] | None = None,
) -> list[str]:
    errs: list[str] = []
    subj = (item.get("subject") or "").strip().lower()
    if subj == "review":
        errs.append("workshop must not produce subject=review")
    elif subj not in ("math", "comm"):
        errs.append(f"subject must be math|comm, got {item.get('subject')!r}")
    l3_id = item.get("l3_id") or ""
    if l3_id not in syll:
        errs.append(f"l3_id not in syllabus: {l3_id}")
    else:
        expected_l2 = syll[l3_id]["l2"]
        if item.get("l2") and item.get("l2") != expected_l2:
            errs.append(f"l2 mismatch: item={item.get('l2')} syllabus={expected_l2}")
        syll_subj = syll[l3_id].get("subject")
        if subj and syll_subj and subj != syll_subj:
            errs.append(f"subject mismatch: item={subj} syllabus={syll_subj}")

    form = item.get("item_form")
    if form not in ALLOWED_FORMS:
        errs.append(f"item_form must be blank|proof_outline, got {form!r}")

    goal = item.get("ability_goal")
    if goal not in ALLOWED_GOALS:
        errs.append(f"ability_goal must be compute|construct, got {goal!r}")

    if question_looks_like_mcq(str(item.get("question") or "")):
        errs.append("MCQ/recognize pattern detected in question")
    if str(item.get("item_form") or "").lower() in {"mcq", "recognize", "choice"}:
        errs.append("forbidden item_form (mcq/recognize)")

    diff = item.get("difficulty")
    if diff not in (None, "", "hit"):
        if str(diff).lower() == "basic":
            errs.append("difficulty must be empty or hit (not basic)")

    errs.extend(_check_cdps(item.get("cdps")))
    errs.extend(_check_solution(item.get("solution")))

    atom_id = item.get("atom_id") or ""
    book_id = item.get("book_id") or ""
    if subj == "comm":
        if not atom_id:
            errs.append("comm items require atom_id in Zhou book")
        elif not str(atom_id).startswith("zhou."):
            errs.append(f"atom_id must be zhou.*, got {atom_id!r}")
        if book_id != "zhou_comm":
            errs.append(f"book_id must be zhou_comm for comm, got {book_id!r}")
    elif atom_id:
        if not str(atom_id).startswith("zhou."):
            errs.append(f"atom_id if set must be zhou.*, got {atom_id!r}")
        if book_id != "zhou_comm":
            errs.append(f"book_id must be zhou_comm when atom_id set, got {book_id!r}")

    meta = item.get("meta") or {}
    sources = (
        set(allowed_sources)
        if allowed_sources is not None
        else {"cloud_cursor_workshop"}
    )
    if isinstance(meta, dict):
        src = meta.get("source")
        if src and src not in sources:
            want = "|".join(sorted(sources)) or "(none)"
            errs.append(f"meta.source expected {want}, got {src!r}")

    for req in ("id", "subject", "l2", "l3_id", "question", "answer", "techniques", "solution"):
        if not item.get(req) and item.get(req) != 0:
            errs.append(f"missing required field: {req}")

    if require_judge_accept:
        if not judge:
            errs.append("missing companion *.judge.json")
        else:
            dec = judge.get("decision")
            if dec != "accept":
                errs.append(f"judge.decision must be accept for keep, got {dec!r}")

    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate bank_workshop incoming items")
    ap.add_argument(
        "incoming_dir",
        nargs="?",
        default=str(ROOT / "data" / "bank_workshop" / "incoming"),
    )
    ap.add_argument("--syllabus-comm", default=DEFAULT_COMM)
    ap.add_argument("--syllabus-math", default=DEFAULT_MATH)
    ap.add_argument("--require-judge-accept", action="store_true", default=True)
    ap.add_argument("--no-require-judge-accept", dest="require_judge_accept", action="store_false")
    args = ap.parse_args()

    syll: dict[str, dict] = {}
    syll.update(index_syllabus(load_syllabus(args.syllabus_comm)))
    syll.update(index_syllabus(load_syllabus(args.syllabus_math)))

    d = Path(args.incoming_dir)
    if not d.is_absolute():
        d = ROOT / d
    if not d.exists():
        print(f"incoming dir missing: {d}", file=sys.stderr)
        return 2

    files = sorted(
        p
        for p in d.rglob("*.json")
        if p.is_file() and not p.name.endswith(".judge.json") and "rejected" not in p.parts
    )
    if not files:
        print(f"no item JSON in {d}")
        return 0

    failed = 0
    for path in files:
        item = load_item(path)
        judge_path = path.with_name(path.stem + ".judge.json")
        judge = load_item(judge_path) if judge_path.exists() else None
        errs = check_item(item, syll, args.require_judge_accept, judge)
        pay = payload_err(item)
        if pay:
            errs.append(f"payload:{pay}")
        rel = path.relative_to(d) if path.is_relative_to(d) else path
        if errs:
            failed += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK   {rel}")

    print(f"checked={len(files)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
