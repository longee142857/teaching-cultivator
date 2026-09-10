# 周炯槃《通信原理》atom library (delivery candidate)

Read-only delivery drop for Cursor 验收. **Not production-wired.**

This directory is a candidate atom SQLite for 周炯槃《通信原理》第4版（考纲范围 Ch2–11）. CK/CV already accepted the pack contents. Cultivate / RAG / `KB_PATH` / `data/teaching.db` are unchanged. A `zhou_sqlite` backend is **out of scope** until 恒宇 nods.

## Status

**Blocker:** the binary delivery pack is not in this tree yet.

Searched, in order:

1. GitHub Release / draft asset named like `zhou_comm_atoms_delivery.tar.gz` on `longee142857/teaching-cultivator` — **none published, no drafts, no assets**
2. Workspace / artifacts / other repos reachable from this agent — **not present**

Expected next step: a follow-up push extracts the real tarball into this directory (especially `zhou_comm.db` ≈ 6MB). Until then, files other than `sources/syllabus_comm.json` (copied from repo SSOT) and this README are placeholders.

See `MISSING_ASSETS.md`.

## Purpose

Give reviewers a frozen, attributable textbook atom DB they can smoke **without** merging it into the cultivate loop. Merge / RAG wiring is documented in `HANDOFF.md` and **must not be executed** from this PR.

## Counts (from the accepted delivery pack; not re-measured here)

| Measure | Count |
|---------|-------|
| Pages | 433 |
| Paragraphs | 6532 |
| Atoms | 411 |
| Syllabus L3 coverage | 149 / 150 |

**L3 gap:** `comm.analog_mod.nbfm`（窄带调频）. The id exists in `sources/syllabus_comm.json`; the atom DB does not cover it.

## Layout (delivery pack)

```
data/zhou_comm/
  zhou_comm.db          # SQLite (~6MB) — MISSING in this commit
  schema.sql
  query_api.py          # smoke: python query_api.py demo
  HANDOFF.md            # merge steps; do not execute
  bench.json
  ingest_report.json
  issues.jsonl
  README.md             # this file
  progress/             # day-00.md … day-12.md, l3-gaps.md
  qa/                   # sample-day-*.json
  sources/syllabus_comm.json
  sources/TASK.md
  tools/insert_atoms.py
```

## Smoke

From this directory (stdlib only; no cultivate imports):

```bash
python query_api.py demo
```

If `zhou_comm.db` is present, the script lists tables and row counts. If it is absent, it exits non-zero and prints the blocker.

Do **not** point `KB_PATH` here. Do **not** ingest into `data/teaching.db`. Do **not** deploy/sync teaching cloud from this PR.

## Merge

Follow `HANDOFF.md` only after 恒宇 nods. This PR does not implement `zhou_sqlite` and does not change RAG.
