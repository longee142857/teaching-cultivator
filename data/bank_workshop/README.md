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

隔离脚本与 CK 操作说明（工作目录 / DB / 备份 / 红线）：  
`tool-scripts/tools/bank-workshop/README.md`

合 master 后 **@ CK**，由他在调度树 ff 后执行（不要假设 SSH）：

```bash
cd /home/ubuntu/teaching-cultivator
cp -a data/teaching.db data/teaching.db.bak-$(date +%Y%m%d-%H%M%S)   # 勿 git add
python3 tool-scripts/tools/bank-workshop/import_incoming.py          # 默认 dry-run
python3 tool-scripts/tools/bank-workshop/import_incoming.py --apply
```

- `kp` ← workshop **L2 名**；`l3_id` ← `l3_id`。`subject` 仅 math/comm。
- `validate_bank_payload` 不过则 failed、不入库、不 move。
- insert 后走 `apply_judge_verdict(..., verdict='pass', reasons=['workshop_accept'])`。
- 只动 items/item_kcs；不发钉钉、默认不重启。失败不半挪。

## Isolation
Workshop artifacts live under `data/bank_workshop/` in this repo only. Do not wire cultivate*.py to this folder automatically. Live import is the isolated script above, run by CK after merge.
