# Bank workshop (isolated) — human accept flow

**尚未入库，等人验收。** These drafts are **NOT** in the live item bank.

工坊只产 **math / comm**，**禁止 `subject=review`**（错题复盘始终由原机 19:00 当场出题）。

## Inventory (Bot 水位，不是全库 30)

Bot 补货目标（ready+pass、未消耗）：

- 当前原子：**2–5** 道（过关是 2 连对）
- 下一原子：最多 **1–2** 道预放
- **单批上限 30**；到上限或水位满即停。不要按全库 ready=30 回流补货。

## Layout
- `AUTHOR_PROMPT.md` / `CRITIC_PROMPT.md` — reusable cloud prompts
- `schema.example.json` — example item
- `batch1_targets.json` — first batch L3 targets
- `incoming/YYYY-MM-DD/*.json` — author drafts
- `incoming/YYYY-MM-DD/*.judge.json` — critic decisions
- `imported/YYYY-MM-DD/` — `--apply` 成功后从 incoming 移入
- `validate_incoming.py` — hard checks vs syllabus URLs/paths

## How to accept (human)
1. Run `python3 data/bank_workshop/validate_incoming.py --require-judge-accept` (from repo root; scans all `incoming/YYYY-MM-DD/`)
2. Review accepted items for pedagogy / correctness. `solution` must be an object (`steps` ≥2); `cdps` must be an object list (≥2, each with `technique`) — **not** integer counts or a solution string.
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

- `kp` ← workshop **L2 名**；`l3_id` ← `l3_id`。`subject` 仅 math/comm；**拒绝 review**。
- 通信题硬闸：`atom_id` 必须在周书库存在。
- `validate_bank_payload` 不过则 failed、不入库、不 move。
- insert 后走 `apply_judge_verdict(..., verdict='pass', reasons=['workshop_accept'])`。无 accept judge **不会**自动 pass。

教材例题（蒲和平竞赛教程）目录 / 标签 / CK 命令：`tool-scripts/tools/textbook-ingest/README.md`。
- 只动 items/item_kcs；不发钉钉、默认不重启。失败不半挪。

## Isolation
Workshop artifacts live under `data/bank_workshop/` in this repo only. Do not wire cultivate*.py to this folder automatically. Live import is the isolated script above, run by CK after merge.
