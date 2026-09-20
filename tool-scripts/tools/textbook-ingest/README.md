# textbook-ingest → teaching.db import

隔离入库。不改 `cultivate.py` / `cultivate_bank.py` / `learner/item_bank.py` / `learner/db.py` / `prompts` / `web`。

教材例题由 knowledge regulator 落到：

`data/textbook_ingest/puheping_math_contest_v2/`

（可分子目录；导入递归扫 `**/*.json`。）

脚本：

- `tool-scripts/tools/textbook-ingest/import_textbook.py`（默认扫上述目录）
- 或 `tool-scripts/tools/bank-workshop/import_incoming.py --incoming data/textbook_ingest/puheping_math_contest_v2`

`schema.example.json` / `*.example.json` **不入库**（仅 schema 样例）。`rejected/` 不扫。

**禁止** `meta.source=cloud_cursor_workshop`（该 source 已在库内 quarantine）。workshop 工坊题仍走 bank-workshop，且 **不会** 因本路径自动 `pass`。

## 标签

| 字段 | 值 |
|------|-----|
| `id` | 前缀 `tx-pu-…` |
| `meta.source` | `textbook_example` |
| `ref_source` | `textbook:puheping_math_contest_v2`（JSON 已有则保留） |
| `meta.book_id` | `puheping_math_contest_v2` |
| `kp` | **`l2`（L2 名）** |
| `l3_id` | `l3_id` |
| `atom_id` | math 可空 |
| `subject` | `math` \| `comm`（不为 review 槽） |

`quality_basis` 写在 `meta`（教材原解）。入库：`insert_bank_item(..., status='ready')` 后 `apply_judge_verdict(verdict='pass', reasons=['textbook_example'])`。不要求 `*.judge.json`。

## After merge (CK)

合 master 后 **@ CK** 在调度树 ff 执行。不要假设 SSH、不要写密钥。本 PR **不写** `teaching.db`。

```bash
cd /home/ubuntu/teaching-cultivator
git pull   # 或 ff 到已合入的 master

# 导入前备份（勿 git add）
cp -a data/teaching.db data/teaching.db.bak-$(date +%Y%m%d-%H%M%S)

# 1) 默认 dry-run：扫 textbook_ingest，不写库、不 move
python3 tool-scripts/tools/textbook-ingest/import_textbook.py \
  --db /home/ubuntu/teaching-cultivator/data/teaching.db

# 等价：显式 --incoming
python3 tool-scripts/tools/bank-workshop/import_incoming.py \
  --incoming data/textbook_ingest/puheping_math_contest_v2 \
  --db /home/ubuntu/teaching-cultivator/data/teaching.db

# 2) 确认 imported / skipped / failed 后正式入库
python3 tool-scripts/tools/textbook-ingest/import_textbook.py --apply \
  --db /home/ubuntu/teaching-cultivator/data/teaching.db
```

- 工作目录：`/home/ubuntu/teaching-cultivator`
- DB：`/home/ubuntu/teaching-cultivator/data/teaching.db`（与练习树共用；**只在调度树跑**）
- 无 DB 时 dry-run 仍可扫描/校验并提示；`--apply` 在库文件不存在时退出，不会新建生产库
- 教材 JSON 留在 `textbook_ingest/`（不搬到 `bank_workshop/imported/`）

## CLI

| 参数 | 说明 |
|------|------|
| `--incoming DIR` | 扫描根；wrapper 默认 `data/textbook_ingest/puheping_math_contest_v2` |
| `--db PATH` | 库路径；默认 `$TEACHING_DB` 或 `data/teaching.db` |
| `--dry-run` | 默认开启；只校验+打印 |
| `--apply` | 真正写库；覆盖 dry-run |
| `--limit N` | 最多处理 N 个题 JSON |
