# Bank workshop (isolated) — human accept flow

**尚未入库，等人验收。** These drafts are **NOT** in the live item bank.

## Layout
- `AUTHOR_PROMPT.md` / `CRITIC_PROMPT.md` — reusable cloud prompts
- `schema.example.json` — example item
- `batch1_targets.json` — first batch L3 targets
- `incoming/YYYY-MM-DD/*.json` — author drafts
- `incoming/YYYY-MM-DD/*.judge.json` — critic decisions
- `imported/YYYY-MM-DD/` — `--apply` 成功后从 incoming 移入
- `validate_incoming.py` — hard checks vs syllabus URLs/paths

## How to accept (human)
1. Run `python3 data/bank_workshop/validate_incoming.py incoming/2026-09-16 --require-judge-accept` (from repo root)
2. Review accepted items for pedagogy / correctness.
3. 验收通过后走隔离入库脚本（见下方「入库」），不要让 cultivate*.py 自动扫本目录。
4. Never point cultivate*.py at this folder automatically.

## 入库

隔离脚本：`tool-scripts/tools/bank-workshop/import_incoming.py`  
操作说明：`tool-scripts/tools/bank-workshop/README.md`

合仓后由 CK 在教学云调度树 `git pull`，先 dry-run，再：

```bash
python3 tool-scripts/tools/bank-workshop/import_incoming.py          # 默认 dry-run
python3 tool-scripts/tools/bank-workshop/import_incoming.py --apply  # 写 teaching.db 并 move
```

- 只导入 `incoming/` 下 `decision==accept` 的题；**不导入** `rejected/`。
- 写入 `insert_bank_item` 后立刻 `apply_judge_verdict(..., verdict="pass")`，否则日推抽不到（默认 pending）。
- `subject` 仅 math/comm；不为复习槽服务。
- 成功后文件落到 `data/bank_workshop/imported/<yyyy-mm-dd>/`。

## Isolation
Workshop artifacts live under `data/bank_workshop/` in this repo only. Do not wire cultivate*.py to this folder automatically. Live import is the isolated script above, run by CK after merge.
