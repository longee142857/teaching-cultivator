# bank-workshop → teaching.db import

隔离入库脚本。不改 `cultivate.py` / `cultivate_bank.py` / `learner/item_bank.py` / `learner/db.py` / `prompts` / `web`。

脚本：`tool-scripts/tools/bank-workshop/import_incoming.py`

只扫描 `data/bank_workshop/incoming/**/*.json`（排除 `*.judge.json` 与 `rejected/`）。同 stem 必须有 `*.judge.json` 且 `decision==accept`，否则跳过。`subject` / `bank_subject` 仅 `math` | `comm`（不为复习槽服务）。

**不要**把 `cloud_cursor_workshop` 自动当 pass：无 accept judge 一律 SKIP。教材例题是另一条路径，见 `tool-scripts/tools/textbook-ingest/README.md`（`--incoming data/textbook_ingest/puheping_math_contest_v2`，`meta.source=textbook_example`）。

## 字段

| DB | workshop |
|----|----------|
| `kp` | **`l2`（L2 名）**，不是 l3_id |
| `l3_id` | `l3_id` |
| `difficulty` | `hit` 或空；禁止 `basic` |
| `ref_source` | `cloud_cursor_workshop` |
| `meta` | 原 meta + `source=cloud_cursor_workshop` + `workshop_id=<item.id>` |
| `solution` | 必须是 `{steps, final_answer, techniques_used}` |
| `cdps` | 必须是对象列表（≥2，每条有 `technique`） |

结构化题先过 `learner.item_bank.validate_bank_payload`；不过则记 **failed**、不入库、不 move（不要硬写占位 CDP）。

现有 incoming 草稿若 `cdps` 仍是整数（workshop 作者格式），会 `FAIL map:cdps_not_object_list`，需改成对象列表后再 `--apply`。`solution` 字符串会规范成 `{steps, final_answer, techniques_used}`。`validate_incoming` 的整数 cdps 闸对对象列表按 `len(cdps)` 检查。

## 写入（正式审判 API，不是裸 UPDATE）

1. `get_store().insert_bank_item(..., status='ready', atom_id=, book_id=)`（insert 默认 `quality_tier=pending`）
2. workshop 已有 accept judge：再 `apply_judge_verdict(iid, verdict='pass', reasons=['workshop_accept'], confidence=1.0)`
3. 幂等依赖 `(subject, q_hash)` `ON CONFLICT`；同题再跑会 update。`meta.workshop_id` 便于审计

只动 `items` / `item_kcs`。禁止动 learners / attempts / pushes / BKT / 会话 / `.env`。不发钉钉，默认不重启。

成功才把题 JSON + judge 移到 `data/bank_workshop/imported/<date>/`。失败不半挪（insert/审判失败则文件留在 incoming；move 失败则库里已有题、文件仍留 incoming，可再跑——ON CONFLICT update）。

## After merge (CK)：调度树

合 master 后 **@ CK** 由他在调度树 ff 执行。不要假设 SSH、不要写密钥。

```bash
cd /home/ubuntu/teaching-cultivator
git pull   # 或 ff 到已合入的 master

# 导入前备份（勿 git add）
cp -a data/teaching.db data/teaching.db.bak-$(date +%Y%m%d-%H%M%S)

# 1) 默认 dry-run：不写库、不 move
python3 tool-scripts/tools/bank-workshop/import_incoming.py \
  --db /home/ubuntu/teaching-cultivator/data/teaching.db

# 2) 确认 imported / skipped / failed 后正式入库
python3 tool-scripts/tools/bank-workshop/import_incoming.py --apply \
  --db /home/ubuntu/teaching-cultivator/data/teaching.db
```

- 工作目录：`/home/ubuntu/teaching-cultivator`
- DB：`/home/ubuntu/teaching-cultivator/data/teaching.db`（与练习树共用；**只在调度树跑**）
- 无 DB 时 dry-run 仍可扫描/校验并提示；`--apply` 在库文件不存在时退出，不会新建生产库

## CLI

| 参数 | 说明 |
|------|------|
| `--db PATH` | 库路径；默认 `$TEACHING_DB` 或 `data/teaching.db` |
| `--incoming DIR` | 扫描根，默认 `data/bank_workshop/incoming`；教材目录见 textbook-ingest README |
| `--imported DIR` | move 目标根，默认 `data/bank_workshop/imported` |
| `--dry-run` | 默认开启；只校验+打印 |
| `--apply` | 真正写库；覆盖 dry-run |
| `--no-move` | `--apply` 时写库但不移动文件 |
| `--limit N` | 最多处理 N 个题 JSON |
