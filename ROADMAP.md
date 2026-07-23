# Roadmap (public)

## Current shape

- DingTalk Stream bot + cultivate loop + agent tools
- Syllabus-backed selection, mastery write-back, evidence-gated authoring
- Optional digests / GitHub trending as side channels
- Structured item seeds consumed at runtime; ingest/refine can live in a sibling knowledge pipeline

## Direction

| Track | Intent |
|-------|--------|
| Content | Grow structured exam/textbook seeds subject by subject |
| Authoring | Keep refuse-to-author semantics; deepen evidence quality |
| Mastery | Preserve stable keys; extend ability/item-form without breaking write-back |
| Ops | Keep credentials out of git; document env contracts only |

## Storage conventions (generic)

- Runtime state: `data/` (most files gitignored)
- Syllabus seeds: `data/syllabus_*.json`
- Example weights: `data/weights.example.json` → copy to `data/weights.json`
- Optional structured seeds: `data/daily_records/structured/{math,comm}/` (local)

Historical private notes and host-specific paths are intentionally omitted from this public roadmap.
