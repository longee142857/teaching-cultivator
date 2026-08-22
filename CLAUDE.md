# Contributor / agent notes

Public guidance for humans and coding agents working in this repository.

## 项目定位：维护期，只优化不叠仓（2026-08-22 起）

本项目进入**维护期**：只做优化、修 bug、简化，**不再叠加新的功能层**。

- 项目本体并不庞大；维护困难来自预想过多——旁路子系统、集成层、为假想需求预留的抽象越叠越多。
- 新想法先过一道闸：**现有模块内能否解决？** 能 → 改现有代码；不能 → 默认不做，除非用户明确拍板且能说清删掉什么旧东西来换。
- 禁止：新增集成目录（integrations/*）、新增旁路服务/端口、为"以后可能用到"留接口和配置项。
- 鼓励：删死代码、合并重复路径、砍掉没人用的开关。

## Role of this repo

Runtime for an adaptive exam-cultivation bot: schedule → decide → evidence-gated author → deliver → grade → mastery write-back. DingTalk is the primary IM channel.

## Layout

```
modules/                目标六模块（拆分中）：items / store / capability / bridge / notify / frontend
modules/capability/     LearnerParams = BKT(L2) + 域 η；EvidenceBundle 导出
modules/notify/         仅通知 + FRONTEND_BASE_URL 深链（答题/讲解不在 IM）
modules/PARKED.md       旁路资讯 / IM 全量 UX 降级清单
main.py                 entry: Stream + scheduler (+ optional kb_cache HTTP)
config.py               env / .env only — no hardcoded secrets
cultivate.py            cultivate loop（推送：bank pick，默认不 live author）
cultivate_bank.py       分时段预生成 → items status=ready
cultivate_judge.py      题库审判层（双槽质检，劣质降权）
grade.py                grading + mastery + CDP 对齐
orchestrate.py          polish / delivery-side checks
quality_gate.py         reject / retry rules
agent/                  legacy ReAct harness（交互改 DSH / 前端）
decide/                 LLM call helpers
deliver/                DingTalk(通知化), system_api, media；digests park
learner/                syllabus, weights, RAG, SQLite store, item_bank, exams
learner/db.py           teaching.db SSOT（pushes/items/attempts/…）
learner/item_bank.py    缺口选规格 / pick / CDP 对齐与可归因过滤
learner/kp_edit.py      L3 知识点提案→确认→落盘（唯一写入路径，审计）
prompts/                templates + format rules
data/                   syllabus seeds; runtime state mostly gitignored
scripts/                acceptance tests and ops helpers
```

新代码优先 `from modules.…`。能力参数红线：BKT mastery ≠ 事件概率；η 未标定仅相对序。

## Hard rules

1. **No secrets in git.** Use `.env` / environment variables. See `.env.example`.
2. **Do not invent absolute machine paths** in committed code; use env (`KB_PATH`, `KB_QUERY_HELPER`, `DAILY_RECORD_DIR`, …).
3. **RAG_STRICT defaults on.** Weak retrieval should refuse authoring unless explicitly debugging with `RAG_STRICT=0`.
4. **Push and agent tools share policy.** Chat shortcuts must not bypass cultivate gates.
5. **Runtime learner files stay local** (`answer-log.jsonl`, conversation ids, `kb_cache/store.json`, `teaching.db`, …).
6. **知识点写入只经 `learner/kp_edit.py`**：只允许追加 **L3** 到已存在 L2；**绝不新建 L2**（BKT 掌握度主键挂 L2）；必须经确认卡片 + 审计，未确认一律不落盘。
7. **推送/列表/当前题以 SQLite 为权威**（`learner/db.py`）。MD/JSON 镜像仅导出或兼容，不得单独冒充成功落库。
8. **日推默认从 ready 题库抽取**（`BANK_LIVE_FALLBACK=0`）。YAML structured 是 **RAG/风格种子**，不是题源；题源是 `cultivate_bank` 预生成。

## 预出题库 + CDP + 审判（2026-08-12）

- **补货**：`cultivate_bank.PREGEN_SLOTS` 分时段、每槽最多 1 道；按薄弱 KP/技巧缺口选规格再 author；入库 `status=ready` + `techniques` / `solution` / `cdps`（≥2）
- **抽题**：`pick_ready_item` 顺序 KP+technique → KP → L1 → 任意；同档按 `quality_score`（pass > pending > poor）；候选 `LIMIT 40`（非全库遍历最优）
- **CDP**：题级写死；批改对齐 id；仅 `attributable` 失败进入技巧/能力信号（对齐占位 `missing_from_grade` 等不计）
- **审判**：每日约 08:30 / 17:30；机器硬闸 + `review_item` 异模型；不合格 `quality_tier=poor` 压抽题权重，不删题
- **解答**：`items.answer` 出题层；结构化 `items.solution` 入库前抽取；`show_solution` 优先渲染 steps
- **学员身份（Cow）**：桥写 `data/pi_active_learner.json`；Pi `teaching-api-client` 解析 `X-Learner-Id`（勿死绑 env owner）
- 验收：`scripts/_test_item_bank.py`；结案叙事见 `D:\cc\logs\SESSION_2026-08-12.md`（本机日志，不进仓）

## 交互层 Agent 工具（2026-07-31）

`agent/tools.py` 工具按权限分三类：

- **读**：`list_knowledge_points`（全考纲 L2+L3）、`kb_query`（小库只读，用 `peek` 不增命中计数）、`find_record_entry` 等既有工具
- **回填登记**：`kb_enqueue`（只进队列 `kb_request_queue.jsonl`，由本机教材 Chroma 回填；`upsert` 直写证据仅限本机同步，Agent 不可直写）
- **知识点写入（最小实现）**：`propose_add_kp` → 确认卡片 → `confirm_add_kp` / `cancel_add_kp`
  - `propose_add_kp` 只登记提案并发确认卡片，**不写考纲**
  - 确认卡片按钮 dtmd 回传 `确认添加知识点 <token>`，`agent/agent.py` 的 `_KP_CONFIRM_RE` 正则直连 bypass（不依赖弱模型理解），落盘由 `kp_edit.confirm_l3` 执行
  - l3_id 自动生成（取该 L2 现有点分前缀 + `k{n}`，含 pending 提案占用 id 去重）
  - 提案存 `data/kp_proposals.json`（staff 校验，跨 learner 不可确认）；所有写入落 `data/kp_edit_audit.jsonl`

## 系统调用面 + Pi（2026-08-09）

**主线**：本仓是**可调用系统**（调度/培养/BKT + 白名单 HTTP）；交互 agent（Pi 等）在仓外，经 API 使用能力。Pi 配置/session/**不进本仓 git**。

### System API（任意 agent）

- 实现：`deliver/system_api.py`；契约：`docs/system-api.md`
- 默认 `http://127.0.0.1:8770`；`Authorization: Bearer $SYSTEM_API_TOKEN` + `X-Learner-Id`
- 白名单工具表见 `docs/pi-tools-whitelist.md`（与 API 对齐）
- **禁止**经 API：`github_push`、裸写 weights/answer-log、`decide()`/调度、改源码

### Pi 交互层（主机侧，非本仓）

- 云端：`~/.pi/agent/extensions/`（`protect-teaching` 路径守卫 + `teaching-api-client` 调 System API）
- 保留 Pi 通用 `bash`/`write`/`edit`；官方 `tool_call` **拦截对教学仓根的裸写**
- 钉钉唤醒：`PI_RPC_ENABLED=1` → `agent/pi_rpc_bridge.py`（TCP 或 `PI_RPC_CMD`）
- 会话树：`PI_SESSION_DIR/learners/{id}.jsonl`；推送后 `[NEW_PUSH]` + fork；指针 `data/learners/{id}/pi_session.json`
- 仓内 `pi-tools.ts` 为历史草稿，已 deprecated

### 定时推送 / `decide()` / 双周卷组卷

**交互 agent 不可调用**；仍属调度器与系统规则路径。

### 参数链路可观测（2026-08-02）

- 每次 BKT record 追加一行 `data/learners/<sid>/param_audit.jsonl`（ts/kp/applied/reason/source/mastery）
- `refine-queue` 的 `type` 已按来源拆分：`grade_incorrect`（grade 答错抬权）/ `weak_self_report`（真·用户自述薄弱）/ `decay`
- `knowledge_point=="未分类"` 或 `quarantined=True` 的条目被隔离：`get_kp_mastery`/`get_all_kp_mastery`/快照/`decide` 均跳过
- `RATE_LIMIT_MAX=5`（24h 内同 KP 最多 5 次有效更新，防刷保留）

## 双周卷个人化（2026-07-31）

- **身份**：学员在 H5 前置页输入**纯数字编号**（每次进入都要输入，无记忆）；uid=编号，草稿/批改/BKT 按编号各算各的。不再依赖钉钉 JSAPI / corpId / HTTPS。
- **草稿**：作答自动防抖保存 `POST /e/{t}/draft`，按 `(paper_id, uid)` 存 `data/exam_bank/drafts/`；重开输入编号后恢复（有草稿提示「已恢复 + 重新开始」），提交后清除。
- **按人存卷**：答卷/批改文件 `answers/<pid>_<uid>_answer.md` / `_grade.md`；`submit_answer_md(md, paper_id, user_id)`，网页提交在 `bind_learner(uid)` 内执行。
- **批改反馈**：`submit_answer_md` 汇总含**得分**（`得分：N/100`）+ 每题掌握度 `before→after`；调 `grade_answer` 时传 `kp_name=L2` + `subject`，掌握度落到考纲正确 L2 → 与每日做题共用 BKT → 自然并入周报趋势。
- **agent 查看**：`get_exam_result(paper_id[, user_id])` 返回某人对某卷的批改报告 + 作答。
- **前端**：`web/static/exam.html` 编号门（无 localStorage 记忆）；`exam_web.py` identify 端点保留但前端不再用。

## 双周卷编题（2026-07-31）

- **节奏/题数**：隔 14 天周日 08:00，数学 + 通信各一份；**目标 7 题，保底 3 题**（`QUESTIONS_PER_SUBJECT=7`，`run_biweekly_issue` 要求 `n_ok>=3`）。
- **混合采样**（`learner/biweekly_exam.py` `_pick_units`）：约一半配额给**热考点**（高 L2 权重）保底能发出高质量题；其余给**冷门考点**（低 L2 权重 = 抽题优先级低 = 不常考）主动摸底，打破「不常考→没数据→更不考」的恶性循环。选考点分散 L2，每章一题优先。
- **冷门放宽 RAG**：冷门考点经 `_author_one(allow_low_rag=True)` → `generate(exam_allow_low_rag=True)` 放宽 RAG 硬闸——无教材证据也允许出题（试卷目的=检测会不会，非出高质量训练题）。每日推送的硬闸不受影响（默认参数行为不变）。
- **强制大题**：能力池 `compute/construct/transfer`，模型偶发写选择题则丢弃重试一次，两次仍像选择宁缺毋滥。

## Syllabus / mastery

- L2 syllabus alignment for math and communications tracks (`data/syllabus_*.json`).
- Selection combines weights and mastery; recent picks are demoted.
- Ability-cycle / item-form logic lives under `learner/ability_cycle.py` (mastery keys remain at the designed grain — do not casually re-key without a migration plan).
- 新增子考点用 `learner/kp_edit.py`（见「交互层 Agent 工具」），不要手改 `syllabus_*.json` 绕过审计。

## Optional external KB

Production evidence can come from `learner/kb_cache` plus an optional helper process:

- `KB_QUERY_HELPER` — script that reads JSON on stdin and prints snippets JSON
- `KB_PYTHON` — interpreter for that helper
- `KB_PATH` / `KB_LIB` — if importing sibling knowledge-system libraries

Without these, strict mode will correctly refuse low-evidence authoring.

## 教材证据分科（kb_cache / source_hints）

`learner/rag_retrieve.py` 把 L3 `source_allow` 映射为检索 `source_hints`；**数学不再把「教材」扩成含卓里奇的大杂烩**。

| 分科 | 主路径 hints（培养闸） | Chroma 拓展（不进主闸） |
|------|------------------------|-------------------------|
| calc | 同济《高等数学》 | 卓里奇《数学分析》 |
| linalg | 丘维声《高等代数》 | — |
| prob | 盛骤 + 茆诗松 | — |
| comm | 周炯槃 + 樊昌信 | — |

- 考纲 L3 的 `source_allow` 宜写具体书名（或「教材」+ 真题）；warm 时必须传 `unit_id`，否则数学会落到三科主书并集（仍不含卓里奇）。
- 小库 `data/kb_cache/store.json` 是运行时证据；云端用本机 warm 后的 store 同步即可，不必在云上跑 embedding。
- **勿**恢复已废弃的 `explain_anchors` / 重学 YAML 旁路。

## Tests

Prefer `scripts/_test_*.py` for gate regressions. Do not claim green without running them.

## Out of scope for agents

- Committing `.env`, private session logs, or production conversation identifiers
- Expanding scope into unrelated monorepo paths
- Declaring “done” when acceptance scripts fail
