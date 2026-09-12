# Day 11
- db: 6279168 bytes, integrity_check: ok
- pages / paragraphs / atoms / atom_spans / atom_l3 / terms : 433 / 6532 / 411 / 1464 / 582 / 1368
- 本批：只读查询 API（`query_api.py`）+ 延迟 bench + L3 抽检；**未改写** pages/paragraphs/atoms/spans（热路径无 embed/LLM）
- L3 已映射（confidence≥0.6，distinct）：149（相对 syllabus 150：99.33%）

## 产物
- `query_api.py`：只读 SQLite API
  - `get(print_page, paras=[...])` → 段落原文 + `paragraph_id`（paras 为页内 seq；缺省=整页）
  - `lookup(term)` → atoms + spans（`print_page` + `paragraph_id`）；先 `terms` 精确命中，miss 时走 `paragraphs_fts` trigram
  - `l3(l3_id)` → 该考点 atoms + locators（含 confidence）
  - 可 import（`from query_api import get, lookup, l3`）或 CLI：`python3 query_api.py {get|lookup|l3|bench|qa|demo}`
- `bench.json`：库打开一次，每 op 重复 50 次，记 p50/p99
- `qa/sample-day-11.json`：随机 20 个已映射 L3（seed=20260911），校验均返回 print_page + paragraph_id

## Bench（p99 目标：get<3ms；lookup/l3<10ms）
| op | args | n | p50_ms | p99_ms | target | pass |
|----|------|---|--------|--------|--------|------|
| get | print_page=1, paras=[1, 2, 3, 4] | 50 | 0.0145 | 0.0314 | <3.0 | ✓ |
| lookup | term='ISI' | 50 | 0.031 | 0.0741 | <10.0 | ✓ |
| l3 | l3_id=comm.coding.block.matrix | 50 | 0.1244 | 0.1683 | <10.0 | ✓ |

- bench.all_pass = True
- locator_ok = {'get': True, 'lookup': True, 'l3': True}

## QA
- 路径：`qa/sample-day-11.json`
- n=20，all_pass=True
- 每条含 l3_id、atoms[].print_page、atoms[].paragraph_ids、pass/fail

## issues
- issues.jsonl 总行数：21（本日未新增）

## 明日计划
- Day 12：`HANDOFF.md` + 全库完整性验收清单；**停在交付候选，不合并教学**

## 合并状态
- 未合并（未写 teaching.db / 未改 cultivate / 未上教学云）
