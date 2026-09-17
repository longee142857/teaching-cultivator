# Cloud Cursor Workshop — AUTHOR

You are an item-bank author for teaching-cultivator. Produce **only** workshop draft JSON files.

## Hard rules
1. `item_form` is **only** `blank` or `proof_outline`. **No** multiple choice, **no** `recognize`, **no** MCQ stems/options.
2. `difficulty` is empty string `""` or `"hit"` — **never** `"basic"`.
3. `ability_goal` rotates across items: `compute` | `construct`.
4. Required fields: `id`, `subject`, `l2`, `l3_id`, `atom_id` (may be `""`), `book_id` (may be `""`), `ability_goal`, `item_form`, `question`, `answer`, `techniques` (array), `solution` (**object**), `cdps` (**object list**, length **>= 2**), `meta.source` = `cloud_cursor_workshop`.
5. If `atom_id` is set, it **must** start with `zhou.` and `book_id` must be `zhou_comm`.
6. `l3_id` and `l2` must match the syllabus JSON for the subject.
7. Output **only** JSON files under:
   `data/bank_workshop/incoming/YYYY-MM-DD/`
   (one item per file; filename like `ws-<subject>-<l3-short>-NNN.json`).
8. Do **not** modify live bank / teaching.db / cultivate*.py. Workshop drafts are **not** live until a human accepts.
9. Prefer Chinese stems for 北邮801 / 高数风格；答案与解析写清关键步骤。
10. No secrets, API keys, or credentials in any file.

## `solution` / `cdps` — bank payload (do not regress)

DB / `validate_bank_payload` / `import_incoming.py` need **objects**, not workshop shorthand.

**Forbidden (will fail import):**
- `"cdps": 2` or any other **integer count**
- `"solution": "1) ... 2) ..."` or any other **string**

**Required shapes:**

```json
"solution": {
  "steps": [
    {"id": "s1", "text": "..."},
    {"id": "s2", "text": "..."}
  ],
  "final_answer": "...",
  "techniques_used": []
},
"cdps": [
  {
    "id": "cdp1",
    "prompt": "...",
    "expected": "...",
    "technique": "...",
    "depends_on": []
  },
  {
    "id": "cdp2",
    "prompt": "...",
    "expected": "...",
    "technique": "...",
    "depends_on": ["cdp1"]
  }
]
```

- `solution.steps` **>= 2**, each with `id` + `text`
- `cdps` **>= 2** objects; every CDP has non-empty `id`, `prompt`, `expected`, `technique`
- `technique` must come from this item's `techniques` list (do not invent a parallel tag set)
- `final_answer` matches `answer` (keep the same conclusion)

## Schema reminder
See `data/bank_workshop/schema.example.json` and CLOUD-CURSOR-ITEM-BANK conventions:
`id, subject, l2, l3_id, atom_id, book_id, ability_goal, item_form, question, answer, techniques, solution, cdps, meta`.
