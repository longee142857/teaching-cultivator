# DSH 导师团（练习台讲师后端）· v3

仓库副本：`integrations/dsh-mentor-team/`

| 端点 | 作用 |
|------|------|
| `POST /api/v1/tutor/chat` | 讲师/助教对话；`Accept: text/event-stream` 时返回 **SSE 流式**，否则 JSON |
| `GET /api/v1/agent/manifest` | manifest（version=3, readOnly, tools, streaming） |

角色：`auto` / `lecturer` / `assistant`。**只读工具按角色最小权限**：

| 角色 | 工具（只读） | 数据源 |
|------|--------------|--------|
| 讲师 | `practice_get_item` `show_solution` `kb_query` `list_knowledge_points` | system_api:8770 → practice_web:8768 → demo |
| 助教 | `get_learner_params` `get_capability_evidence` `get_learner_snapshot` `list_today_questions` `build_report` `practice_bootstrap` | 同上 |

执行链：**system_api(:8770，`X-System-Token`)** → **practice_web(:8768)** → **本地演示数据（前缀「【演示数据】」）**。LLM（DeepSeek 直连）**按需调用工具**取数，工具结果成为 `citations`（逐条证据引用）。批改/命题仍由教学运行时负责（边界闸）。

**通用版 host.js**：Node standalone（云端 `process` 存在）走 `web.fetch` 全功能；真实 DSH（`process` 不可用）走 **subprocess curl** 执行器（`curlRequest`，`C:\Windows\System32\curl.exe` 兜底）。

---

## 接线（B 档，单点）

```bash
# 云端 teaching-mentor.service 经 EnvironmentFile 注入 .env：
TUTOR_BACKEND_URL=http://127.0.0.1:61900
PRACTICE_API_BASE=http://127.0.0.1:8768
SYSTEM_API_BASE=http://127.0.0.1:8770
SYSTEM_API_TOKEN=<与 system_api 同 key，勿入库>
DEEPSEEK_API_KEY=...          # 或 LLM_API_KEY
LLM_BASE_URL=https://api.deepseek.com/v1
TUTOR_MODEL=deepseek-chat
```

`deliver/practice_web.py`：客户端带 `Accept: text/event-stream` 时**透传 SSE 流**；否则走原 JSON 代理；未配置 `TUTOR_BACKEND_URL` 仍 501。

运行：`sudo systemctl restart teaching-mentor`（standalone.mjs，VPS 无 GUI）。

### 本地 DSH GUI（本机插件）接教学系统

本机 DSH 插件（`mentor-1`）与云端同一份 host.js。`process` 不存在 → 用 subprocess curl 执行器。要连云端教学系统，先建 SSH 隧道，再写配置文件：

```bash
# 隧道（本地端口 → VPS 服务）
ssh -i ~/.ssh/ccc.pem -N -L 8768:127.0.0.1:8768 -L 8770:127.0.0.1:8770 ubuntu@154.8.196.179
```

```json
// {workspace}/.mentor-team/config.json（勿提交仓库）
{
  "SYSTEM_API_TOKEN": "……",
  "DEEPSEEK_API_KEY": "……"
}
```

未配置/不可达时：工具回落演示数据（带「【演示数据】」标注），LLM 不可用回落规则应答，均显式声明，不冒充真实学情。

---

## 记忆（T0/T1/T2）

- T0 工作状态：`phase`（idle/awaiting_answer/reviewing/planning）+ `todos` + `activeItemId`，随工具调用更新，注入 LLM 上下文。
- T1 情节：线程（内存，≤40 条/线程）。
- T2 语义：`card.json`（weak/notes/milestones），`mentor.export`/`mentor.clearCard` 导出与清空。

## 边界

- 批改 → 练习台 `POST /api/v1/practice/submit`；命题/复评 → teaching 定时或人工。
- 导师团可写 **Capability Brain 事件**（`POST /api/v1/capability/events`），不批改、不出题。
- 脱机：`detached:true` + 演示数据；工具不可达时如实返回「暂未取到」，禁止编造。
