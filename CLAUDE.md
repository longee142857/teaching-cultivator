# Contributor / agent notes

Public guidance for humans and coding agents working in this repository.

## Role of this repo

Runtime for an adaptive exam-cultivation bot: schedule → decide → evidence-gated author → deliver → grade → mastery write-back. DingTalk is the primary IM channel.

## Layout

```
main.py                 entry: Stream + scheduler (+ optional kb_cache HTTP)
config.py               env / .env only — no hardcoded secrets
cultivate.py            cultivate loop
grade.py                grading + mastery update
orchestrate.py          polish / delivery-side checks
quality_gate.py         reject / retry rules
agent/                  ReAct-style tool harness + memory blocks
decide/                 LLM call helpers
deliver/                DingTalk, WeCom, media, digests
learner/                syllabus, weights, RAG contract, ability cycle, exams
prompts/                templates + format rules
data/                   syllabus seeds; runtime state mostly gitignored
scripts/                acceptance tests and ops helpers
```

## Hard rules

1. **No secrets in git.** Use `.env` / environment variables. See `.env.example`.
2. **Do not invent absolute machine paths** in committed code; use env (`KB_PATH`, `KB_QUERY_HELPER`, `DAILY_RECORD_DIR`, …).
3. **RAG_STRICT defaults on.** Weak retrieval should refuse authoring unless explicitly debugging with `RAG_STRICT=0`.
4. **Push and agent tools share policy.** Chat shortcuts must not bypass cultivate gates.
5. **Runtime learner files stay local** (`answer-log.jsonl`, conversation ids, `kb_cache/store.json`, …).

## Syllabus / mastery

- L2 syllabus alignment for math and communications tracks (`data/syllabus_*.json`).
- Selection combines weights and mastery; recent picks are demoted.
- Ability-cycle / item-form logic lives under `learner/ability_cycle.py` (mastery keys remain at the designed grain — do not casually re-key without a migration plan).

## Optional external KB

Production evidence can come from `learner/kb_cache` plus an optional helper process:

- `KB_QUERY_HELPER` — script that reads JSON on stdin and prints snippets JSON
- `KB_PYTHON` — interpreter for that helper
- `KB_PATH` / `KB_LIB` — if importing sibling knowledge-system libraries

Without these, strict mode will correctly refuse low-evidence authoring.

## Tests

Prefer `scripts/_test_*.py` for gate regressions. Do not claim green without running them.

## Out of scope for agents

- Committing `.env`, private session logs, or production conversation identifiers
- Expanding scope into unrelated monorepo paths
- Declaring “done” when acceptance scripts fail
