# Roadmap (public)

## Current shape（拆分中）

目标模块：`items` + `store` + `capability` + `bridge` + `notify` + `frontend`（见 `modules/`）。

本轮已落地：

- 包边界与依赖方向（`modules/README.md`）
- 核心参数 `LearnerParams`（BKT L2 + 域 η）与 EvidenceBundle 导出
- notify 仅通知契约 + `FRONTEND_BASE_URL` 深链
- system_api 挂载 `get_learner_params` / `get_capability_evidence`
- 旁路资讯 / IM 全量 UX 列入 `modules/PARKED.md`

## Direction

| Track | Intent |
|-------|--------|
| Split | 逐步把 `cultivate_*` / `learner/db` 物理迁入 `modules/*`，旧 import 变薄 shim |
| Capability | 题参 (a,d) 标定；η 快照进调度选题；与 capability-prob predict 联调 |
| Notify | 调度推送改为 notify-only；钉钉交互面收缩 |
| Frontend | 答题 / 讲解 UI（所有者自建）经 bridge |
| Agent | DSH 替代 Pi；经 bridge 白名单，配置不进本仓 |
| Cut | 删除或迁出 park 项（trending / digest / 仓内主 agent） |

## Storage conventions (generic)

- Runtime state: `data/` (most files gitignored)
- Syllabus seeds: `data/syllabus_*.json`
- Example weights: `data/weights.example.json` → copy to `data/weights.json`
- Optional structured seeds: `data/daily_records/structured/{math,comm}/` (local)

Historical private notes and host-specific paths are intentionally omitted from this public roadmap.
