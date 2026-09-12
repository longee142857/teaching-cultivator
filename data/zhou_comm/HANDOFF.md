# HANDOFF — 周炯槃《通信原理》原子库（交付候选）

> 执行者：knowledge regulator（Grok Bot）  
> 日期：2026-09-10  
> **状态：交付候选，未合并。合并由 Cursor 在本仓只读接入，经恒宇点头后再同步教学云。**

## 1. 产物位置（隔离工作区）

```
/workspace/zhou-comm-atoms/
  schema.sql
  zhou_comm.db              # 唯一真相（+ 可能的 -wal/-shm）
  query_api.py              # 只读三入口
  bench.json
  ingest_report.json
  issues.jsonl
  progress/day-00.md … day-11.md
  progress/l3-gaps.md
  qa/sample-day-*.json
  sources/                  # PDF / MinerU / OCR / syllabus / TASK
  tools/                    # insert_atoms + dayNN_atoms.json
  HANDOFF.md                # 本文件
```

**禁止**把上述文件直接写进 `teaching-cultivator/data/` 或教学云。由 Cursor 搬迁。

## 2. 库快照（SQL）

| 项 | 值 |
|----|-----|
| integrity_check | ok |
| db bytes | 6279168 |
| pages | 433 |
| paragraphs | 6532 |
| atoms | 411 |
| atom_spans | 1464 |
| atom_l3 | 582 |
| terms | 1368 |
| L3 覆盖 (≥0.6) | 149/150 = 99.33% |
| L3 缺口 | `comm.analog_mod.nbfm` |
| page_offset | 13（pdf_page − 13 = print_page；文件名=PDF 页码） |

atoms by created_day: {1: 40, 2: 35, 3: 38, 4: 36, 5: 48, 6: 38, 7: 36, 8: 140}  
atoms by chapter: {2: 38, 3: 36, 4: 38, 5: 40, 6: 73, 7: 42, 8: 23, 9: 84, 10: 22, 11: 15}

## 3. Day 12 验收清单

- [x] `zhou_comm.db` 可复制、`PRAGMA integrity_check` = ok
- [x] 物理层覆盖考纲页范围（Ch2–11 已灌）；空页见 Day0 `ingest_report` / progress
- [x] 每个 atom 有 locator；多日 `qa/sample-day-*.json` 抽检
- [x] L3 覆盖 ≥80%（实际 99.3%）；缺口见 `progress/l3-gaps.md`
- [x] `query_api.py` 三入口 + `bench.json` 达标（get/lookup/l3 p99 均远低于 3ms/10ms）
- [x] **未** 改 teaching 源码、**未** 写 `teaching.db`、**未** 上教学云
- [x] 本 HANDOFF 只描述合并步骤，**未执行合并**

## 4. 给 Cursor 的合并步骤草稿（写步骤，不跑）

1. 把 `zhou_comm.db`（及若有的 WAL 先 `PRAGMA wal_checkpoint(FULL)` 或一并拷贝）放到教学仓只读路径，用 env（如 `ZHOU_COMM_DB` / `KB_PATH` 的 zhou 后端）配置，**不要**把盘符写死进 git。
2. `rag_retrieve` 增加 backend `zhou_sqlite`：调用本库 `get` / `lookup` / `l3` 语义，返回 `atom_id` + `print_page` + `paragraph_id`（禁止只回散文）。
3. 出题硬闸改为「命中 ≥1 atom 且 `atom_l3` 对得上本题 L3」。
4. `kb_cache` 的 key 日后改为 `atom_id`（本任务不做）。
5. 同步教学云是 **最后一步**，且仅在本机验收通过、恒宇点头之后。

## 5. 已知缺口 / 注意

- `comm.analog_mod.nbfm`：书中无独立窄带调频专节，未强行映射。
- Ch1/12/13 与附录：物理层已灌，原子降权（非本轮重点）。
- 习题段已跳过，不入库为考点 atom。
- MinerU token 仅在 `tools/mineru-pack/secrets.env`，默认不重 OCR。

## 6. 查询冒烟

```bash
cd /workspace/zhou-comm-atoms
python3 query_api.py demo
python3 query_api.py bench
```

bench 摘要：{"get": 0.0314, "lookup": 0.0741, "l3": 0.1683}
