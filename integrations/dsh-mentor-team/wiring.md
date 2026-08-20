# DSH 导师团（练习台讲师后端）

仓库副本：`integrations/dsh-mentor-team/`  
本地开发目录：`D:\DSH\mentor-team`（与仓库保持同内容）

只保留教学项目能用上的能力：

| 端点 | 作用 |
|------|------|
| `POST /api/v1/tutor/chat` | 讲题 / 只读诊断；契约兼容 `docs/practice-api.md` |
| `GET /api/v1/agent/manifest` | DSH 侧 manifest（version=2, readOnly） |

角色：`auto` / `lecturer` / `assistant`。只读接地：`practice/bootstrap` + `practice/params`（必要时 `practice/item`）。**不**批改、**不**出题、**不**写 BKT/η。

---

## 推荐接线（B 档）

练习台前端继续打本仓 `practice_web`；`tutor/chat` 由本仓代理到 DSH：

```bash
# .env
TUTOR_BACKEND_URL=http://127.0.0.1:61900
# 可选：DSH host 读教学 API 的基址（默认 8768）
# PRACTICE_API_BASE=http://127.0.0.1:8768
```

`deliver/practice_web.py`：未配置 `TUTOR_BACKEND_URL` 时仍返回 501；配置后透传 body + `X-Learner-Id`。

公网（VPS，对齐双周卷）：

1. Cloudflare DNS：`practice.longee.icu` A → VPS IP（橙云可开）
2. nginx：`scripts/practice_web.nginx.conf.example`
3. 进程：`PRACTICE_ALLOW_DEMO_SEED=0` + `TUTOR_BACKEND_URL=http://127.0.0.1:61900` 起 `python -m deliver.practice_web`
4. DSH：桌面 GUI 用 `host.js`+`client.js`；**VPS 无 GUI 时**用同目录 `standalone.mjs`：

```bash
PRACTICE_API_BASE=http://127.0.0.1:8768 PORT=61900 \
  node integrations/dsh-mentor-team/standalone.mjs
```

导师团可写 Capability Brain 事件（不批改、不出题）：

- 对话：「写入事件：考研专业课通过 domains=comm,signals」
- API：`GET/POST /api/v1/capability/events` → `data/capability_events.json`

5. 钉钉：`FRONTEND_BASE_URL=https://practice.longee.icu`

也可以 nginx：

```nginx
location = /api/v1/tutor/chat {
    proxy_pass http://127.0.0.1:61900;
    proxy_set_header X-Learner-Id $http_x_learner_id;
}
```

---

## A 档：DSH 浮层（client.js）

GUI 右下角「导师团」。learner 取自 URL `?learner=`，否则读练习台 localStorage，默认 `stu_1024`；`item`/`push` 同样取自 URL。

---

## 边界

- 批改 → 练习台 `POST /api/v1/practice/submit`
- 命题 / 复评 → teaching 定时或人工
- 脱机：演示数据 + `detached:true`，禁止出题建议
