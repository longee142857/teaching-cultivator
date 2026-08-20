# Parked / cut from main path

为消减叠仓，下列能力**不再属于 teaching 主路径**。代码可暂留仓库，但调度默认关闭、文档不再宣称为核心。

| 项 | 原位置 | 处理 |
|----|--------|------|
| GitHub trending 资讯推送 | `deliver/github_trending/` | park；不进 cultivate / notify |
| X digest | `deliver/x_digest.py` | park |
| 企业微信全量交互 bot | `deliver/wecom_bot.py` | park；notify 可保留 webhook 文本通知 |
| 钉钉内答题 / 讲解 / 卡片操作 | `deliver/dingtalk_bot.py` 交互面 | 降级为 **通知渠道**；答题与讲解迁前端 |
| 仓内 Pi tools 草稿 | `pi-tools.ts` | deprecated（已有说明） |
| 仓内 ReAct agent 作主交互 | `agent/` | legacy；交互改 DSH / 前端，本仓经 bridge |
| 双周卷钉钉发图主路径 | `deliver/exam_image.py` 等 | 保留库能力；投递改通知+前端链接 |

恢复任一 park 项须单独开分支，并证明不破坏六模块依赖方向。
