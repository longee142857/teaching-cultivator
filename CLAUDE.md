# Contributor / agent notes

Public guidance for humans and coding agents working in this repository.

## Role of this repo

Runtime for an adaptive exam-cultivation bot: schedule → decide → evidence-gated author → deliver → grade → mastery write-back. DingTalk is the primary IM channel.

## Layout

```
main.py                 entry: Stream + scheduler (+ optional kb_cache HTTP)
config.py               env / .env only — no hardcoded secrets
cultivate.py            cultivate loop
grade.py                grading + mastery update
orchestrate.py          polish / delivery-side checks
quality_gate.py         reject / retry rules
agent/                  ReAct-style tool harness + memory blocks
decide/                 LLM call helpers
deliver/                DingTalk, WeCom, media, digests
learner/                syllabus, weights, RAG contract, ability cycle, exams
learner/kp_edit.py      L3 知识点提案→确认→落盘（唯一写入路径，审计）
prompts/                templates + format rules
data/                   syllabus seeds; runtime state mostly gitignored
scripts/                acceptance tests and ops helpers
```

## Hard rules

1. **No secrets in git.** Use `.env` / environment variables. See `.env.example`.
2. **Do not invent absolute machine paths** in committed code; use env (`KB_PATH`, `KB_QUERY_HELPER`, `DAILY_RECORD_DIR`, …).
3. **RAG_STRICT defaults on.** Weak retrieval should refuse authoring unless explicitly debugging with `RAG_STRICT=0`.
4. **Push and agent tools share policy.** Chat shortcuts must not bypass cultivate gates.
5. **Runtime learner files stay local** (`answer-log.jsonl`, conversation ids, `kb_cache/store.json`, …).
6. **知识点写入只经 `learner/kp_edit.py`**：只允许追加 **L3** 到已存在 L2；**绝不新建 L2**（BKT 掌握度主键挂 L2）；必须经确认卡片 + 审计，未确认一律不落盘。

## 交互层 Agent 工具（2026-07-31）

`agent/tools.py` 工具按权限分三类：

- **读**：`list_knowledge_points`（全考纲 L2+L3）、`kb_query`（小库只读，用 `peek` 不增命中计数）、`find_record_entry` 等既有工具
- **回填登记**：`kb_enqueue`（只进队列 `kb_request_queue.jsonl`，由本机教材 Chroma 回填；`upsert` 直写证据仅限本机同步，Agent 不可直写）
- **知识点写入（最小实现）**：`propose_add_kp` → 确认卡片 → `confirm_add_kp` / `cancel_add_kp`
  - `propose_add_kp` 只登记提案并发确认卡片，**不写考纲**
  - 确认卡片按钮 dtmd 回传 `确认添加知识点 <token>`，`agent/agent.py` 的 `_KP_CONFIRM_RE` 正则直连 bypass（不依赖弱模型理解），落盘由 `kp_edit.confirm_l3` 执行
  - l3_id 自动生成（取该 L2 现有点分前缀 + `k{n}`，含 pending 提案占用 id 去重）
  - 提案存 `data/kp_proposals.json`（staff 校验，跨 learner 不可确认）；所有写入落 `data/kp_edit_audit.jsonl`

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

## Tests

Prefer `scripts/_test_*.py` for gate regressions. Do not claim green without running them.

## Out of scope for agents

- Committing `.env`, private session logs, or production conversation identifiers
- Expanding scope into unrelated monorepo paths
- Declaring “done” when acceptance scripts fail
