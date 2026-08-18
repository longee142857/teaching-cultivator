# teaching modules（叠仓拆分）

目标形态：六个相对独立的模块，经明确契约关联；本仓不再兼任「IM 全量交互 + 旁路资讯」叠仓。

| 模块 | 目录 | 职责 | 本轮状态 |
|------|------|------|----------|
| 题目机制 | `modules/items/` | 出题、预生成、审判、质检 | facade + 契约 |
| 存储 | `modules/store/` | SQLite SSOT | facade → `learner/db.py` |
| 能力量化 | `modules/capability/` | BKT(L2) + IRT η(域) 统一参数 | **本轮核心重构** |
| 桥 | `modules/bridge/` | 前端 / 未来 DSH 的 HTTP 契约 | 新 API 面 + 兼容旧 system_api |
| 推送 | `modules/notify/` | **仅通知**（链到前端答题） | 新契约；IM 全量 UX 降级 |
| 前端 | `modules/frontend/` | 答题 / 讲解 UI | 用户自有；本仓只留挂载点 |

## 依赖方向（禁止反向）

```
items ──写──► store
capability ─读写─► store
bridge ──读/写编排──► items | store | capability
notify ──读 store 元数据──► 发通知（不含题面作答）
frontend ──经 bridge──► store / items / capability
```

- `capability` **不**调用 `notify` / IM bot。
- `notify` **不**渲染讲解、不收答案（答案走 frontend → bridge）。
- 旁路资讯（GitHub trending / X digest 等）移出主路径，见 `PARKED.md`。

## 与 sibling 仓边界

| 仓 | 边界 |
|----|------|
| `capability-prob` | 事件 DAG / Monte Carlo 预测；teaching 导出 EvidenceBundle 只读喂它。域 η 估计逻辑可在 teaching 运行时复用副本，**学术真相仍以 capability-prob papers/engine 为准**。 |
| `DeepTutor` | agent-native 能力/工具分层参考；不并仓。 |
| `DSH` | 计划替代 Pi agent；经 bridge 白名单调用，配置不进本仓。 |

旧顶层包（`cultivate.py` / `learner/` / `deliver/` / `agent/`）本轮保留为兼容实现，新代码优先 `from modules.…`。
