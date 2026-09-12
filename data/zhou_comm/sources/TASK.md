---
audience: Grok Bot（12 天长跑；教材信息化，不是出题）
id: ZHOU-COMM-ATOMS-12D
created: 2026-09-07
owner: 刘桓宇 / Cursor 验收
status: ready-to-run
merge: forbidden-until-accepted
---

# 周炯槃《通信原理》原子库 · 12 日任务书

你是执行者，不是架构师。本文件是全部规则。12 天只交 **一本可查询的定位库**，不要改教学运行时，不要「顺手」接到培养循环，**不要上云合并**。

一句话目标：把周炯槃《通信原理》（第 4 版，考纲范围 Ch2–11）做成独立 SQLite，能在毫秒级按 **印张页 + 段** 或 **L3 考点** 取出原文，供日后 teaching 当出题证据。BKT 主键仍是 L2，禁止把段落当成掌握度节点。

---

## 0. 合并红线（最高优先级）

**12 个工作日之内，以及验收通过之前，禁止任何「上云 / 合并 / 接生产」。**

禁止：

- 写入 `teaching.db`（本机或云端）
- `scp` / `rsync` / git push 到教学云机（`ubuntu@154.8.196.179`）的 teaching 数据目录
- 改 `cultivate.py` / `rag_retrieve.py` / `learner/db.py` / syllabus 作为「提前接线」
- 把未完成库设为 `KB_PATH` 或替换 Chroma
- 新建 L2、改 BKT 键、往 `syllabus_comm.json` 里塞段落 id
- 宣称「先合并一章到云上试试」

允许：

- 在 **隔离工作目录** 里写 `zhou_comm.db`、schema、报告、抽检 JSON
- 每天把工作副本打成一份交付包，留给恒宇/Cursor 抽检（本机或 Bot 云电脑本地盘，**不是** 教学云）
- 向恒宇要源文件（若你这边没有 OCR）

**Day 12 结束 ≠ 已合并。** 你停在「交付候选」。合并由 Cursor 在本仓做只读接入，经恒宇点头后再同步教学云。你的最后一条消息必须是交付清单 + 「等待验收，未合并」。

---

## 1. 你在做什么 / 不做什么

### 做

1. 从 **按页 OCR** 确定性灌入物理层（页、段）。
2. 用 LLM 只写概念层：`atoms` + `atom_spans` + 术语 + 对齐现有 L3。
3. 提供只读查询：`get(page, paras)` / `lookup(term)` / `l3(l3_id)`，本机 p99 < 10ms（不含首次打开文件）。
4. 每天留下可 `SELECT COUNT` 的进度，防自己偷懒。

### 不做

- 不出题、不改题库、不跑 cultivate、不审题
- 不把整本 `MinerU_*.md` 切成 chunks 当完成
- 不上向量库当热路径（Chroma / 新 embed 都不要作为主检索）
- 不引入 Postgres / Neo4j
- 不重 OCR、不调 MinerU（源文已有）
- 不把樊昌信混进本库（那是另一本书）

---

## 2. 输入（缺则停，向恒宇要，不要编）

优先用按页 OCR，不用整本 md 切段。

| 用途 | 路径（本机） |
|------|----------------|
| PDF | `D:\参考书籍\通信原理 [Principles of Communications] (周炯槃,庞沁华,续大我,吴伟陵,杨鸿文) (z-library.sk, 1lib.sk, z-lib.sk).pdf` |
| 整本 OCR（只作对照，不作文段 SSOT） | `D:\参考书籍\MinerU_通信原理（周炯槃）.md` |
| 按页 OCR（物理层 SSOT） | `D:\cc\ai-systems\knowledge-system\data\ocr_pages\通信原理（周炯槃）\page_XXX.md` |
| 考纲 L3 | `D:\cc\ai-systems\teaching-cultivator\data\syllabus_comm.json`（约 150 个 `"id": "comm...."`） |

页码约定（已标定，不要改）：

- `page_offset = 13` → OCR/PDF 页 14 ≈ 印张页 1（以 `ocr_pipeline.py` 为准）
- 库内对外一律存 **印张页 `print_page`**，同时保留 `pdf_page` 便于核对 PDF
- 若抽检发现某章 offset 漂移，记入 `issues.jsonl`，**不要静默改全局 offset**

若你跑在 Grok 云电脑、没有这些盘：

1. 第一天消息里列出缺失文件，等恒宇上传。
2. 上传前不要用网上下载的别的版本替代。
3. 工作目录自建，例如 `/home/user/zhou-comm-atoms/` 或云电脑等效路径。

---

## 3. 隔离工作区（唯一允许写入的地方）

```
<WORK>/
  schema.sql
  zhou_comm.db              # 唯一真相
  ingest_report.json        # Day 0
  progress/day-NN.md        # 每日
  qa/sample-day-NN.json     # 每日抽检
  issues.jsonl              # 页码/公式/对不齐
  query_api.py              # 只读查询
  bench.json                # Day 11 延迟
  HANDOFF.md                # Day 12 给 Cursor 的合并说明（只写步骤，不执行合并）
```

禁止把上述文件直接写进 `teaching-cultivator/data/` 或 `knowledge-system/data/`。完成后 Cursor 再搬。

---

## 4. 三层模型（必须按此建表）

```
物理层 paragraphs  ──►  概念层 atoms  ──►  考纲 L3（只映射，不修改 syllabus）
     locator                 可引用陈述              teaching 日后引用 atom_id
```

- 段落 = 证据地址，不是知识点。
- 原子常常跨 2–4 段；一段可服务多个原子。
- `items` / BKT 不在本任务范围。

### 4.1 schema（Day 0 冻结，12 天内不改表名/主键语义）

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE pages (
  print_page INTEGER PRIMARY KEY,
  pdf_page INTEGER NOT NULL,
  chapter TEXT,
  text TEXT NOT NULL,
  checksum TEXT NOT NULL,
  n_chars INTEGER NOT NULL
);

CREATE TABLE paragraphs (
  id TEXT PRIMARY KEY,              -- 冻结：zhou.p{print_page:03d}.s{seq:02d}
  print_page INTEGER NOT NULL REFERENCES pages(print_page),
  seq INTEGER NOT NULL,             -- 页内从 1
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  text TEXT NOT NULL,
  kind TEXT NOT NULL,               -- body|formula|caption|example|footnote|header
  UNIQUE (print_page, seq)
);

CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
  text,
  content='paragraphs',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TABLE atoms (
  id TEXT PRIMARY KEY,              -- zhou.ch{N}.{slug} 稳定、可 diff，禁止 UUID
  type TEXT NOT NULL,               -- definition|theorem|formula|procedure|caveat|example
  name TEXT NOT NULL,
  statement TEXT NOT NULL,          -- 可独立阅读的陈述，但必须有 span
  chapter INTEGER NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  created_day INTEGER NOT NULL
);

CREATE TABLE atom_spans (
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  paragraph_id TEXT NOT NULL REFERENCES paragraphs(id),
  role TEXT NOT NULL,               -- core|context|counterexample
  PRIMARY KEY (atom_id, paragraph_id)
);

CREATE TABLE atom_l3 (
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  l3_id TEXT NOT NULL,              -- 必须已存在于 syllabus_comm.json
  confidence REAL NOT NULL,         -- 0–1；<0.6 进 issues，不算覆盖
  PRIMARY KEY (atom_id, l3_id)
);

CREATE TABLE terms (
  term TEXT NOT NULL,
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  PRIMARY KEY (term, atom_id)
);

CREATE INDEX ix_para_page ON paragraphs(print_page);
CREATE INDEX ix_atom_ch ON atoms(chapter);
CREATE INDEX ix_l3 ON atom_l3(l3_id);
CREATE INDEX ix_terms_term ON terms(term);
```

`meta` 至少写入：`book=通信原理（周炯槃）`、`edition=4`、`page_offset=13`、`schema_rev=1`。

### 4.2 物理层切分规则（确定性，禁止 LLM 切段）

对每个 `page_XXX.md`：

1. 按空行切段；连续公式块（含 `$$` / MinerU 公式标记）合成 `kind=formula`，不要并进前后正文。
2. 图注/表注 → `caption`；明显「例 x-x」→ `example`；页眉页脚噪声 → `header`（可降权，不必原子化）。
3. `id` 一旦写入不得改号。修文只改 `text` 并记 `issues.jsonl`。
4. 空页、纯图页写入 `pages` 但 `paragraphs` 可为 0，报告里点名。

### 4.3 原子硬闸（LLM 产出不合格即丢弃）

每条 atom 必须同时满足，否则不准 INSERT：

- ≥1 条 `atom_spans`，其中 ≥1 条 `role=core`
- `statement` 非空，且不是「见上文」式空话
- `id` 形如 `zhou.ch3.nyquist.criterion`（小写、点分、可猜）
- 公式类 atom 的 core span 必须落在 `kind=formula` 或紧邻公式的 body
- 禁止只有 `statement` 没有 locator
- 禁止把整页打成一个 atom（core spans 一般 ≤ 6 段；超限拆开或记 issue）

L3 映射：

- `l3_id` 必须是 syllabus 里已有 id；对不上就 **不要编新 L3**，写入 `issues.jsonl` 类型 `unmapped_l3`
- 一个 atom 可对多个 L3；一个 L3 应逐渐有多个 atom
- `confidence < 0.6` 不计入覆盖率

---

## 5. 查询 API（Day 11 必须能跑）

`query_api.py` 只读，三种入口，热路径 **只走 SQLite**（主键 / `terms` / FTS5），禁止 embed/rerank/LLM。

```text
get(print_page, paras=[3,4])  → 段落原文 + paragraph_id
lookup(term)                  → atoms + spans（印张页+段号）
l3(l3_id)                     → 该考点全部 atoms + 定位
```

延迟基准（库已打开后，重复 50 次取 p99）：

- `get` p99 < 3ms
- `lookup` / `l3` p99 < 10ms
- 结果必须带 `print_page` 与 `paragraph_id`，禁止只返回散文

---

## 6. 12 日日程与每日闸

每天结束必须同时有：`progress/day-NN.md` + 更新后的 `zhou_comm.db`。闸不过 → 当天不算完成，次日先补，不准跳章刷数量。

考纲优先序（按此排章，不要从绪论刷到附录）：

1. 数字频带 / 数字基带 / 信道编码
2. 确定信号与随机信号 / 信道容量
3. 模拟调制 / 信源编码 / 扩频与多载波
4. 绪论、附录、纯图：只建物理层，原子降权

章号以本书目录为准（Day 0 从目录页抽出 `chapter → print_page 范围` 写入 `ingest_report.json`）。考纲写的是 Ch2–11；Ch1 可灌页但原子不是重点。

| 日 | 产物 | 通过线 | 偷懒形态（直接打回自己） |
|----|------|--------|--------------------------|
| 0 | schema 冻结 + 灌 pages/paragraphs + FTS 建好 + TOC 页图 | 页数与 OCR 文件数差 ≤ 2%；抽 10 页人工/自检段切合理；`ingest_report.json` 含空页列表 | 用整本 md 切 chunk；不写 checksum |
| 1–8 | 每天 1–2 章原子 | 该章：atoms ≥ 25（过短章 ≥ 15）；≥90% atom 有 core span；`qa/sample` 随机 10 条全部带页+段 | 只写摘要；UUID id；整页一原子 |
| 9 | `atom_l3` | syllabus **150 个 L3** 中 ≥80% 至少 1 条 `confidence≥0.6`；缺口表 `progress/l3-gaps.md` | 用 L2 名糊上去；编造 l3_id |
| 10 | `terms` + 易混对 | 高频术语（奈奎斯特/ISI/匹配滤波/香农/眼图/滚降/维特比 等）lookup 有命中；至少 15 组易混 aliases | 同义词不管 |
| 11 | `query_api.py` + `bench.json` | 三种入口都能跑；延迟达标；20 个抽查 L3 都能给出印张页+段号 | 查询再包一层 LLM |
| 12 | `HANDOFF.md` + 全库完整性 | 见 §7；**停在交付，不合并** | 擅自 scp / 改 teaching |

Day 1–8 建议按 TOC 把 Ch2–11 切成 8 个工作包（一天一包，过短章合并、过长章拆两天）。具体页范围以 Day 0 TOC 为准，写进当天 `progress`。

---

## 7. Day 12 验收清单（全部勾上才叫「交付候选」）

- [ ] `zhou_comm.db` 可复制、WAL 可 `PRAGMA integrity_check`
- [ ] 物理层覆盖考纲页范围（Ch2–11）；空页已列表
- [ ] 每个 atom 有 locator；抽 20 条核对 PDF/印张页
- [ ] L3 覆盖 ≥80%，缺口有名单
- [ ] `query_api.py` 三入口 + bench 达标
- [ ] **未** 改 teaching 源码、**未** 写 `teaching.db`、**未** 上教学云
- [ ] `HANDOFF.md` 只描述 Cursor 应做的合并步骤（见下），你未执行

`HANDOFF.md` 应写给 Cursor 的合并步骤草稿（你写步骤，你不跑）：

1. 把 `zhou_comm.db` 放到教学仓只读路径（env，不要写死盘符进 git）
2. `rag_retrieve` 增加 backend `zhou_sqlite`，返回 `atom_id` + `print_page` + `paragraph_id`
3. 出题硬闸改为「命中 ≥1 atom 且 atom_l3 对得上本题 L3」
4. `kb_cache` 的 key 日后改为 `atom_id`（本任务不做）
5. 同步教学云是 **最后一步**，且在本机验收通过之后

---

## 8. 每日 `progress/day-NN.md` 模板

```markdown
# Day NN
- db: <bytes>, integrity_check: ok|fail
- pages / paragraphs / atoms / atom_l3 mapped / terms : n
- 本章或本批：<chapter> print_page a–b
- 新增 atom ids（列表或附件）
- 抽检 10 条：路径 qa/sample-day-NN.json（每条含 atom_id, print_page, paragraph_ids, pass/fail）
- issues 新增条数
- 明日计划
- 合并状态: 未合并
```

计数必须来自 SQL，禁止估。

---

## 9. 沟通

- 恒宇是验收人；架构疑问停下来问，不要自行升级成图数据库或「先接培养循环」。
- 缺源文件 → 停。幻觉一本教材 → 失败。
- 不要把本任务与出题、钉钉、BKT、樊昌信混在同一轮。
- 结束语固定包含：**「12 日交付候选已就绪，等待验收；云端合并未执行。」**
