# Day 08 (partial)

- db: integrity_check: ok
- pages / paragraphs / atoms / atom_spans / atom_l3 / terms : 433 / 6532 / 324 / 1166 / 459 / 990
- 本批仅 INSERT：`tools/day08_ch8_atoms.json`、`tools/day08_ch10_atoms.json`、`tools/day08_ch11_atoms.json`（**未**插入 ch4/ch7，即使文件存在）
- created_day=8；Day1–7 未改动：40/35/38/36/48/38/36

## 插入结果（per file）

| file | drafted | inserted | rejected |
|------|---------|----------|----------|
| day08_ch8_atoms.json | 23 | 23 | 0 |
| day08_ch10_atoms.json | 22 | 15 | 7 |
| day08_ch11_atoms.json | 15 | 15 | 0 |
| **合计** | **60** | **53** | **7** |

### ch10 rejects（core spans > 6）

- `zhou.ch10.pn.sync.capture.track`: too many core spans (8>6)
- `zhou.ch10.walsh.hadamard`: too many core spans (7>6)
- `zhou.ch10.walsh.props.caveat`: too many core spans (7>6)
- `zhou.ch10.ds.bpsk`: too many core spans (8>6)
- `zhou.ch10.dsss.anti.interference`: too many core spans (7>6)
- `zhou.ch10.ocdm.cdma`: too many core spans (8>6)
- `zhou.ch10.scramble.lfsr.selfsync`: too many core spans (7>6)

## SQL 分章计数（created_day=8）

- Ch8：atoms=23；有 role=core：23（100.0%）；L3 已映射：23
- Ch10：atoms=15；有 role=core：15（100.0%）；L3 已映射：15
- Ch11：atoms=15；有 role=core：15（100.0%）；L3 已映射：15
- Day8 合计 atoms：53
- Day8 无 ch4/ch7 行

## 门禁 / QA

- 单章 count gate（≥25）：Ch8/Ch10/Ch11 均未过（partial，预期）
- core gate：三章均为 100% 有 core
- QA：暂不要求（待 Day8 全部章节入库后再做）
- 教学合并：未合并

## 阻塞 / 下一步

- 阻塞：Ch10 有 7 条因 core spans>6 被拒，需缩核后重插
- 下一步：处理 ch4/ch7（或按任务书其余 Day8 章节）→ 全章入库后再 QA
