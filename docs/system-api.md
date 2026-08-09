# Teaching System API（任意 agent 调用面）

> 权威契约。白名单与 [`pi-tools-whitelist.md`](pi-tools-whitelist.md) 对齐。  
> Pi / Cursor / curl 均经本接口；**不要**让外部 agent 裸写仓内 `weights` / `answer-log` / 源码。

## 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/health` | 健康检查 + 工具名列表 |
| GET | `/v1/tools` | 工具 schema（参数名/默认值） |
| GET | `/v1/tools/{name}?k=v` | 调用只读/简单工具（query 作参数） |
| POST | `/v1/tools/{name}` | 调用工具；body 为参数对象或 `{ "params": {...} }` |
| POST | `/v1/call` | `{ "tool": "grade_answer", "params": {...}, "learner_id": "..." }` |

默认：`http://127.0.0.1:8770`（env `SYSTEM_API_HOST` / `SYSTEM_API_PORT`）。  
`SYSTEM_API_HTTP=0` 可关闭。

## 鉴权与学员

| Header | 含义 |
|--------|------|
| `Authorization: Bearer $SYSTEM_API_TOKEN` 或 `X-System-Token` | 共享 token；未配置 token 时仅建议本机访问 |
| `X-Learner-Id`（或 `X-Staff-Id`） | 钉钉 staffId / 学员编号；绑定 `bind_learner` |

POST `/v1/call` 也可用 body `learner_id`。

## 白名单工具

### 读

`list_recent_entries` · `find_record_entry` · `get_learner_snapshot` · `get_active_question` · `list_knowledge_points` · `kb_query` · `list_exam_bank` · `get_exam_paper` · `get_exam_result` · `show_solution` · `build_report`

### 动作（写状态由系统闸）

`generate_question` · `grade_answer` · `submit_exam_answer_md` · `adjust_difficulty` · `note_weak_point` · `propose_add_kp` · `confirm_add_kp` · `cancel_add_kp` · `propose_override_grade` · `confirm_override` · `cancel_override` · `kb_enqueue`

### 永不暴露

`github_push` · 裸 BKT/weights · `decide()` · 调度触发 · 改源码

## 响应

```json
{ "ok": true, "tool": "get_active_question", "result": "..." }
```

失败：`{ "ok": false, "error": "..." }`（HTTP 400/401/404）。

`result` 多为工具返回的字符串（与 `agent/tools.py` 一致）。

## 示例

```bash
curl -sS -H "X-Learner-Id: $OWNER_STAFF_ID" -H "Authorization: Bearer $SYSTEM_API_TOKEN" \
  http://127.0.0.1:8770/v1/tools/get_active_question

curl -sS -X POST -H "Content-Type: application/json" \
  -H "X-Learner-Id: $OWNER_STAFF_ID" -H "Authorization: Bearer $SYSTEM_API_TOKEN" \
  -d '{"last_question":"","user_answer":"B"}' \
  http://127.0.0.1:8770/v1/tools/grade_answer
```

## 参数严格度（TS extension vs Python 默认值）

Pi 端 `teaching-api-client.ts` 的 TypeBox schema 可能比 Python 端函数签名更严或更松。调用时以 **HTTP API（Python 端默认值）** 为准，TS 端声明仅约束 Pi LLM 传参。

| 工具 | Python 端默认值 | TS 端声明 | 说明 |
|------|----------------|-----------|------|
| `grade_answer` | `last_question=""`, `user_answer=""` | last_question Optional, user_answer required | 对齐（2026-08-09 后） |
| `kb_query` | `subject="math"`, `kp=""` | subject required, kp required | TS 更严（防御性，防 LLM 忘传） |
| `kb_enqueue` | `subject="math"`, `kp=""` | subject required, kp required | 同上 |
| `get_exam_result` | `paper_id=""` | paper_id required | TS 更严 |
| `submit_exam_answer_md` | `md_text=""` | md_text required | TS 更严（防空卷） |
| `confirm_add_kp` / `cancel_add_kp` | `token=""` | token required | TS 更严 |
| `confirm_override` / `cancel_override` | `token=""` | token required | TS 更严 |
| `list_recent_entries` / `get_learner_snapshot` / `build_report` | `days=7` | days Optional | 一致 |
| `find_record_entry` | `date`, `num=0` | date required, num Optional | 一致 |

> 规则：TS 端更严是"提前拦截"，不会破坏 HTTP 端；调用方始终可带缺省参数。

## Pi 会话指针（约定）

学员目录可写只读指针（非 Pi 源码）：

`data/learners/{safe_id}/pi_session.json`：

```json
{ "session_path": "/home/ubuntu/pi-sessions/learners/{safe_id}.jsonl", "updated_at": "..." }
```

Pi 扩展与 session 文件本身在主机 Pi 家目录，**不进本仓 git**。
