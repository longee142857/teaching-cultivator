# bank-workshop → teaching.db import

隔离入库脚本。不改 `cultivate.py` / `cultivate_bank.py` / `learner/item_bank.py` / `learner/db.py` / `prompts` / `web`。

只扫描 `data/bank_workshop/incoming/**/*.json`（排除 `*.judge.json` 与 `rejected/`）。同 stem 必须有 `*.judge.json` 且 `decision==accept`，否则跳过。`subject` 仅 `math` / `comm`（不为复习槽服务）。

写入走现有入口：

1. `learner.db.get_store().insert_bank_item(...)`（与 `cultivate_bank` 相同）
2. `store.apply_judge_verdict(item_id, verdict="pass", reasons=["bank_workshop_accept"], details=judge)`  
   （`insert_bank_item` 默认 `quality_tier=pending`，日推只抽 `pass`）

硬校验复用 `data/bank_workshop/validate_incoming.py`。

## After merge (CK)：教学云调度树

合仓后由 CK 在调度树执行（本机仓根，不要 SSH）：

```bash
cd /path/to/teaching-cultivator   # 调度树工作副本
git pull

# 1) 先 dry-run（默认：不写库、不 move）
python3 tool-scripts/tools/bank-workshop/import_incoming.py

# 2) 确认汇总 imported / skipped / failed 后再入库
python3 tool-scripts/tools/bank-workshop/import_incoming.py --apply
```

成功后题 JSON + judge 会移到 `data/bank_workshop/imported/<yyyy-mm-dd>/`。

## CLI

| 参数 | 说明 |
|------|------|
| `--db PATH` | 库路径；默认 `$TEACHING_DB` 或 `data/teaching.db` |
| `--incoming DIR` | 扫描根，默认 `data/bank_workshop/incoming` |
| `--imported DIR` | move 目标根，默认 `data/bank_workshop/imported` |
| `--dry-run` | 默认开启；只校验+打印 |
| `--apply` | 真正写库；覆盖 dry-run |
| `--no-move` | `--apply` 时写库但不移动文件 |
| `--limit N` | 最多处理 N 个题 JSON |

无 DB 时 dry-run 仍可跑完扫描/校验，并提示 `--apply` 会失败；`--apply` 在库文件不存在时退出码 2，**不会新建**生产库。

不要把密钥写进命令行或日志。脚本不打印环境变量或 token。
