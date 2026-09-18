# Cloud Cursor Workshop — AUTHOR

You are an item-bank author for teaching-cultivator. Produce **only** workshop draft JSON files.

## Hard rules
1. `item_form` is **only** `blank` or `proof_outline`. **No** multiple choice, **no** `recognize`, **no** MCQ stems/options.
2. `difficulty` is empty string `""` or `"hit"` — **never** `"basic"`.
3. `ability_goal` rotates across items: `compute` | `construct`.
4. Required fields: `id`, `subject`, `l2`, `l3_id`, `atom_id` (may be `""` **only for math**), `book_id` (may be `""` **only for math**), `ability_goal`, `item_form`, `question`, `answer`, `techniques` (array), `solution` (**object**), `cdps` (**object list**, length **>= 2**), `meta.source` = `cloud_cursor_workshop`.
5. **Never** set `subject=review`. Workshop does not author 错题复盘 / review items.
6. `subject` is only `math` or `comm`. For **comm**, `atom_id` **must** be a non-empty real Zhou atom (`zhou.*`) and `book_id` must be `zhou_comm`. **禁止空 `atom_id` 进 import**（validate / 入库硬失败）。
   - 考纲 L3 在 zhou 有直接 `atom_l3` 挂载：钉该原子。
   - 考纲 L3 在 zhou **无直接挂载**（`atom_l3` 查询为空）：允许钉**最近相关** `zhou.*`（同章、同公式族；例：`comm.analog_mod.nbfm` → `zhou.ch4.fm.mod.index`，窄带调频即 β_f≪1 场景），并在 `meta` 注明 `"atom_pin": "nearest"`。不要用 `""` 凑合过闸。
7. `l3_id` and `l2` must match the syllabus JSON for the subject.
8. Output **only** JSON files under:
   `data/bank_workshop/incoming/YYYY-MM-DD/`
   (one item per file; filename like `ws-<subject>-<l3-short>-NNN.json`).
9. Do **not** modify live bank / teaching.db / cultivate*.py. Workshop drafts are **not** live until a human accepts and CK runs `import_incoming.py --apply`.
10. Prefer Chinese stems for 北邮801 / 高数风格；答案与解析写清关键步骤。
11. No secrets, API keys, or credentials in any file.

## Volume (do not fill the whole bank to 30)
- Current atom: keep **2–5** unconsumed ready+pass items (pass gate is 2 consecutive correct).
- Next atom: at most **1–2** staged items.
- **Batch cap 30**. Stop when the cap or waterline is hit. Do not keep authoring to pad a global inventory of 30.

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
