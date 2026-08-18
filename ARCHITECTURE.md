# Architecture

## Target shape（模块拆分，本轮）

六个相对独立模块，经契约关联（详见 `modules/README.md`）：

```
items（出题+审核）──► store（SQLite）
capability（BKT L2 + 域 η）◄──► store
bridge（前端 / DSH）──编排──► items | store | capability
notify（仅通知 + 深链）──读元数据──► store
frontend（答题/讲解）──经 bridge──► …   ← 本仓不实现页面
```

旧顶层包（`cultivate.py` / `learner/` / `deliver/` / `agent/`）本轮保留为兼容实现；
新代码优先 `from modules.…`。旁路资讯与 IM 全量 UX 见 `modules/PARKED.md`。

## Runtime state (BIG-TEACH-013)

SQLite (`DATA_DIR/teaching.db`，可用 env `TEACHING_DB` 覆盖) 是运行时**单一真相源**：

- `items` / `pushes`：出题与推送；当前题 = 该学员可见（公共 `learner_id IS NULL` ∪ 个人）中 `pushed_at` 最新
- `attempts` / `mastery_states`：作答与 BKT 掌握度（`learner/bkt_db.py` 提供 SQLite 版 BKTLogger）
- `ability_snapshots`：可存 `LearnerParams` 快照（BKT + η）
- 月 MD / `*.index.json` / `last_push.json` / `public/last_class.json` / `answer-log.jsonl`：迁移后仅作**只读导出 / 兼容镜像**，不再作为权威

时区约定：所有「今天 / 日期槽」按 `Asia/Shanghai`（UTC+8）解释，DB 存 UTC ISO。

连接统一走 `learner/db.py`（`get_store()`）或 `modules.store.get_store()`；禁止在别处散落 `sqlite3.connect`。

## Capability params（核心重构）

两层能力，禁止混用：

| 层 | 符号 | 粒度 | 用途 |
|----|------|------|------|
| BKT | `p_mastery` | L2 KP | 练习选题 / 复查 / 批改写回 |
| IRT | `η` | calc / linalg / prob | 跨 KP 量化；导出给 capability-prob 事件预测 |

入口：`modules.capability.build_learner_params` → `LearnerParams`。  
写回：`grade` applied 后 `refresh_after_grade` 落 `ability_snapshots`。  
选题：`weak_kp_ranked` 在 weights×(1−mastery) 上叠加域 η 薄弱提权（有观测域）。  
题参：预生成 `insert_bank_item` 写 `meta.irt`；EvidenceBundle 从 items 回填 (a,d)。  
红线：不得把 BKT mastery 直接当作事件成功概率；题参未标定时 η̂ 仅相对序有意义。

## Cultivate path

```
assess → decide → author → rule_gate → review_item → polish/orchestrate → record
                              ↑
                     rag_retrieve / kb_cache (evidence)
         deliver 改为 notify（短通知 + FRONTEND_BASE_URL 深链）
```

Grading: `grade` → `verify_grade` → apply|pending → mastery write-back when applied（并可刷新 η 快照）。

## Model matrix

| Role | Default model | Channel |
|------|---------------|---------|
| Agent (chat / tools) | `deepseek-v4-flash` + thinking max | DeepSeek direct (0731 agentic refresh) |
| author / grade / explain | `deepseek-v4-pro` + thinking | DeepSeek direct |
| review_item / verify_grade | `qwen-plus` | DashScope 北京直连（失败回退 DeepSeek Flash） |
| polish / orchestrate | `deepseek-v4-flash` | DeepSeek direct |

Override via env: `AGENT_MODEL`, `AGENT_THINKING`, `AGENT_REASONING_EFFORT`, `REVIEWER_PROVIDER`, `REVIEWER_MODEL`, `DASHSCOPE_API_KEY`, `DEEPSEEK_MODEL_*`.

## Channels（产品迁徙）

| Channel | Module | Role |
|---------|--------|------|
| Notify | `modules/notify` | **主投递**：短通知 + 前端深链 |
| Bridge API | `modules/bridge` + `deliver/system_api` | 前端 / DSH 白名单 |
| DingTalk Stream | `deliver/dingtalk_bot.py` | 降级为通知通道；答题/讲解迁前端 |
| WeCom | `deliver/wecom_bot.py` | park（可选 webhook 文本通知） |

## Design invariants

1. Evidence gate before author when `RAG_STRICT=1`.
2. Mastery keys stay normalized to syllabus grain (L2).
3. IM 客户端不再承载作答与讲解；通知文案指向前端。
4. Content supply may be external; this repo is the **runtime**.
5. Critique roles (`review_item` / `verify_grade`) stay cross-provider from author/grade via DashScope Qwen when configured.
6. `capability` 不调用 `notify`；`notify` 不收答案。
