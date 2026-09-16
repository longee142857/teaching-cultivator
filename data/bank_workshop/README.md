# Bank workshop (isolated) — human accept flow

**尚未入库，等人验收。** These drafts are **NOT** in the live item bank.

## Layout
- `AUTHOR_PROMPT.md` / `CRITIC_PROMPT.md` — reusable cloud prompts
- `schema.example.json` — example item
- `batch1_targets.json` — first batch L3 targets
- `incoming/YYYY-MM-DD/*.json` — author drafts
- `incoming/YYYY-MM-DD/*.judge.json` — critic decisions
- `validate_incoming.py` — hard checks vs syllabus URLs/paths

## How to accept (human)
1. Run `python3 data/bank_workshop/validate_incoming.py incoming/2026-09-16 --require-judge-accept` (from repo root)
2. Review accepted items for pedagogy / correctness.
3. Only then copy into teaching-cultivator live bank via the normal cultivate/bank path (outside this isolated tree).
4. Never point cultivate*.py or teaching.db at this folder automatically.

## Isolation
Workshop artifacts live under `data/bank_workshop/` in this repo only. Do not wire cultivate*.py or teaching.db to this folder automatically.
