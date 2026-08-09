# Pi 交互层白名单 → tools.py 符号对照表（2026-08-09）

> 依据：`teaching-cultivator/CLAUDE.md`「Pi 交互层白名单」+ `agent/tools.py` 实际函数。
> 用途：Pi tool 注册（`pi-tools.ts`）的权威依据。Pi 只调这些；其余函数内部用，不暴露。

## 一、read:* — 只读（Pi 自由调）

| 白名单 API | tools.py 符号 | 返回 | 写入 |
|-----------|--------------|------|------|
| `list_recent_entries` | `list_recent_entries(days=7)` | 近 N 天题目索引 | 无 |
| `find_record_entry` | `find_record_entry(date, num=0)` | 某条题目全文 | 无 |
| `get_learner_snapshot` | `get_learner_snapshot(days=7)` | 学习指标快照 | 无 |
| `get_active_question` | `get_active_question()` | 当前题（单一真相源） | 无 |
| `list_knowledge_points` | `list_knowledge_points(subject, query)` | 考纲 L2/L3 | 无 |
| `kb_query` | `kb_query(subject, kp)` | 小库只读 peek | 无（不增命中计数） |
| `list_exam_bank` | `list_exam_bank(query, limit)` | 双周卷目录 | 无 |
| `get_exam_paper` | `get_exam_paper(paper_id)` | 试卷全文 | 无 |
| `get_exam_result` | `get_exam_result(paper_id, user_id)` | 批改报告/作答 | 无 |
| `show_solution` | `show_solution()` | 系统生成解答 | 无（不写 BKT） |
| `build_report` | `build_report(days=7)` | 学习周报 | 无 |

## 二、action:* — 动作（调系统，写状态由系统闸决定）

| 白名单 API | tools.py 符号 | 系统内闸 |
|-----------|--------------|---------|
| `generate_question` | `generate_question(subject, kp_hint)` | 走 cultivate/RAG/质检；不绕闸 |
| `grade_answer` | `grade_answer(last_question, user_answer)` | confidence→applied/pending；BKT+weights 在系统内；回显 [KP=][TS=] |
| `submit_exam_answer_md` | `submit_exam_answer_md(md_text, paper_id)` | 同 grade 链 |
| `adjust_difficulty` | `adjust_difficulty(subject, level)` | audit_only，不改 mastery |
| `note_weak_point` | `note_weak_point(subject, kp, reason)` | 只 bump weights（record_bkt=False） |
| `propose_add_kp` | `propose_add_kp(subject, l2, name, aliases)` | 只登记提案，不落盘 |
| `confirm_add_kp` | `confirm_add_kp(token)` | 确认卡 + kp_edit 审计 |
| `cancel_add_kp` | `cancel_add_kp(token)` | 确认卡 + kp_edit 审计 |
| `propose_override_grade` | `propose_override_grade(kp, correct, subject, credit)` | 只登记提案，不落盘 |
| `confirm_override` | `confirm_override(token)` | 确认卡 + override_edit 审计 |
| `cancel_override` | `cancel_override(token)` | 确认卡 + override_edit 审计 |
| `kb_enqueue` | `kb_enqueue(subject, kp, query)` | 只进队列，不直写 Chroma |

## 三、禁止 — Pi 永不可用

| 能力 | tools.py 对应 | 原因 |
|------|--------------|------|
| `github_push` | `github_push(repo_path, commit_msg)` | 权限过大，默认关 |
| 裸写 weights/answer-log | （内部函数） | 绕过闸 |
| 裸 bkt.record / bump_kp_weight | `override_grade` 底层 | 必须经系统 API |
| 改源码 / bash / 装包 | — | 逃逸面 |
| 调 decide() / 调度 / 双周卷组卷 | `generate_question` 的 decide 内部 | Pi 不可调 |

## 四、内部辅助（不暴露给 Pi）

`_uid` / `_read_latest_entry` / `_load_last_push_record` / `_load_last_push_question` /
`_looks_truncated` / `override_grade`（仅 confirm 内部调，不直接暴露）

## 五、Pi tool 注册映射建议

每个 Pi tool = 一个 tools.py 函数 + tool shim：
- 只读（read:*）→ 直接调 Python 函数返回文本
- 动作（action:*）→ 调函数，但写状态由系统闸（confidence/确认卡）决定
- 参数 schema：按函数签名映射（subject enum math/comm/review；level enum basic/intermediate/challenge）
