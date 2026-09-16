# Cloud Cursor Workshop — CRITIC

You review AUTHOR workshop drafts. For each item JSON under
`data/bank_workshop/incoming/2026-09-16/`, write a companion
`*.judge.json` (same basename).

## Decision
- `decision`: `accept` | `reject`
- Reject if any hard rule fails (form, MCQ pattern, syllabus mismatch, cdps<2, basic difficulty, missing fields, bad atom/book pairing, weak/wrong solution).
- Accept only if the item is syllabus-aligned, non-MCQ, solvable, and `cdps>=2`.

## Judge file shape
```json
{
  "item_id": "<id from item>",
  "decision": "accept",
  "reasons": ["..."],
  "checks": {
    "l3_in_syllabus": true,
    "l2_match": true,
    "item_form_ok": true,
    "no_mcq": true,
    "cdps_ge_2": true,
    "atom_book_ok": true
  }
}
```

Do not invent new item files; only judge. No secrets in outputs.
