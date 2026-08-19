# Practice desk API（前端 teaching-shell + 后续 agent）

> 权威契约。实现：`modules/bridge/practice_service.py` + `deliver/practice_web.py`。  
> 讲师 chat **本轮不实现**（`POST /api/v1/tutor/chat` → 501 stub）。

## 服务

| 项 | 值 |
|----|-----|
| 默认基址 | `http://127.0.0.1:8768` |
| 页面 | `GET /practice` → `web/static/teaching-shell.html` |
| 开关 | `PRACTICE_WEB_HTTP=1`（默认开） |
| 鉴权 | `PRACTICE_API_TOKEN`（空则仅建议本机） |
| 批改模式 | `PRACTICE_GRADE_MODE=llm\|ref`（llm 失败自动 `ref_fallback`） |
| 演示种子 | `PRACTICE_ALLOW_DEMO_SEED=1` 时今日无推送可写入三槽演示题 |

深链（钉钉通知）：`/practice?learner={id}&item=i{n}&push={pushId}`

## HTTP 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/practice` | 练习台 shell |
| GET | `/api/v1/agent/manifest` | **给后续 agent 的完整接口清单** |
| GET | `/api/v1/practice/bootstrap?learner=` | 今日槽 + items + 已答 + 薄弱提示 + capability 摘要 |
| GET | `/api/v1/practice/item?learner=&item=&push=` | 单题（深链补全） |
| GET | `/api/v1/practice/params?learner=` | LearnerParams 全量 |
| POST | `/api/v1/practice/submit` | 提交作答 → 批改 → BKT/η（llm）或 ref |
| POST | `/api/v1/tutor/chat` | **501** `tutor_agent_not_wired` + 请求/响应契约 |

Header：`X-Learner-Id`（可替代 query/body `learner`）；`Authorization: Bearer` / `X-Practice-Token`。

### bootstrap 响应（摘要）

```json
{
  "ok": true,
  "learner": "stu_1024",
  "day": "2026-08-19",
  "slots": [
    {"kind":"math","label":"高等数学","window":"08:00–12:00","windowKey":"morning","itemId":"i12","pushId":34}
  ],
  "items": [
    {
      "id": "i12", "itemId": 12, "pushId": 34, "kind": "math",
      "subject": "高等数学", "kp": "…", "title": "…", "stem": "…", "katex": "…",
      "commentOk": "…", "commentBad": "…", "explain": "…",
      "day": "2026-08-19", "backlog": false, "answered": false
    }
  ],
  "answered": {},
  "weakHint": "…",
  "capability": {"eta": {}, "masteryWeak": []},
  "tutor": {"enabled": false, "reason": "tutor_agent_not_wired"},
  "gradeMode": "llm"
}
```

公开 `item` id 为 `i{n}`；不回传标准答案字段。

### submit body

```json
{"learner":"…","item":"i12","push":"34","answer":"…","mode":"ref"}
```

`result`：`correct` / `comment` / `explain` / `submitted` / `status` / `kp` / `gradeMode`；llm 时另有 `masteryBefore`/`masteryAfter`。

### tutor stub

```json
{
  "ok": false,
  "error": "tutor_agent_not_wired",
  "contract": {
    "request": {"learner":"str","item":"str|null","push":"str|null","message":"str","threadId":"str|null"},
    "response": {"reply":"str","streaming":"bool?","citations":"list?"}
  }
}
```

## system_api 工具（`:8770`，供 agent）

| 工具 | 读写 |
|------|------|
| `practice_bootstrap` | 读 |
| `practice_get_item` | 读 |
| `practice_submit` | 写 |
| `practice_agent_manifest` | 读 |
| `get_learner_params` / `get_capability_evidence` | 读 |

需 `X-Learner-Id`。详见 [`system-api.md`](system-api.md)。

## 本地联调

```bash
PRACTICE_ALLOW_DEMO_SEED=1 PRACTICE_GRADE_MODE=ref \
  python -m deliver.practice_web

curl -sS 'http://127.0.0.1:8768/api/v1/practice/bootstrap?learner=demo1'
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"learner":"demo1","item":"i1","push":"1","answer":"0"}' \
  http://127.0.0.1:8768/api/v1/practice/submit
```

浏览器打开 `http://127.0.0.1:8768/practice?learner=demo1`。
