"""Teaching Harness Agent — ReAct loop + memory blocks + 结构化 transcript。

原理（Claude Code 式 dumb loop + Letta-lite blocks）:
  用户消息 → 组装 system(blocks+reminder) + transcript
           → while tool_calls and step < MAX_STEPS:
                 执行工具 → observation 回灌 → 刷新 reminder
           → 纯文本回复 → 落盘 transcript / blocks
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from config import AGENT_MODEL
from agent.tools import (
    generate_question,
    grade_answer,
    show_solution,
    adjust_difficulty,
    override_grade,
    propose_override_grade,
    confirm_override,
    cancel_override,
    build_report,
    github_push,
    find_record_entry,
    list_recent_entries,
    note_weak_point,
    get_learner_snapshot,
    list_exam_bank,
    get_exam_paper,
    submit_exam_answer_md,
    get_exam_result,
    list_knowledge_points,
    kb_query,
    kb_enqueue,
    propose_add_kp,
    confirm_add_kp,
    cancel_add_kp,
)
from agent.memory_blocks import MemoryBlocks
from agent.transcript import Transcript

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 6
ProgressCallback = Callable[[str], None]

# 确认卡片按钮 dtmd 回传文案 → 直连 confirm/cancel，不依赖弱模型理解
_KP_CONFIRM_RE = re.compile(
    r"^(确认|取消)(?:添加)?知识点\s*#?\s*([A-Za-z0-9]+)\s*$"
)
_OVERRIDE_CONFIRM_RE = re.compile(
    r"^(确认|取消)纠正\s*#?\s*([A-Za-z0-9]+)\s*$"
)

SYSTEM_PROMPT = """你叫瑞贝卡，是用户的考研导师，在钉钉群教学。

你有以下工具可用。根据用户需求选最合适的工具，不需要工具就直接回复。
同一次回复里可以连续多步调用工具（例如先 list_recent_entries 再 find_record_entry），
直到信息足够再给用户最终自然语言答复。

## 工具列表

1. generate_question — 出一题。用户说"出题""来一题""数学""通信""换一道同类题""出一道数学题巩固""出一道通信题巩固"等时调用。
   参数: subject(math/comm/review), kp_hint(可选,指定知识点)
   工具返回原始题目内容，直接将其作为回复发给用户，开头加一句自然引导
   「换一道同类题」→ 用当前 active_question 的 subject（缺省 math），kp_hint 尽量沿用当前知识点

2. grade_answer — 批改用户的作答。用户看起来在回答问题或提交答案时调用。
   参数: last_question(可传空), user_answer(用户的回答)

2b. list_exam_bank / get_exam_paper / submit_exam_answer_md / get_exam_result — 双周检测卷题库。
   用户问「双周卷」「试卷库」「交卷」或间隔很久再讨论某份卷时：先 list_exam_bank，再 get_exam_paper。
   用户粘贴整份答卷 md 时调用 submit_exam_answer_md。
   用户问「我上次卷子答得怎么样」「批改结果」「得分」「某题怎么批的」时调用 get_exam_result(paper_id)，
   返回该学员该卷的批改报告 + 作答（含得分与每题判定）。
   **重要**：批改「最近推送」时 last_question 必须传空字符串 ""，服务端会自动读取完整题干；
   禁止把系统提示里的摘要/片段当作 last_question 传入。只有用户明确在答更早一题、
   且你已用 find_record_entry 取到全文时，才把该全文传入 last_question。

3. show_solution — 读题库最新题目 → 调 LLM 现做解答。用户说"答案""解析""不会做""我不会做""要解析""这题咋解"时调用。
   **限制（BIG-TEACH-012b #A1）：用户只答了 A/B/C/D 或极短选项字母时**禁止**调用；先 grade_answer 批改并追问思路**。
   返回格式:
   - "题目：...\n\n解答：..." → 直接发给用户
   - "NO_ENTRY" → 题库为空，让用户先出题
   - "SOLUTION_FAILED|{题目}" → LLM 生成失败，可以重试

3b. override_grade — 用户说「批错了」「这题判错了」「其实我对了」「改一下掌握度」时调用，**只登记纠正提案并发确认卡片，不直接改掌握度**。用户点「确认纠正」后才覆盖。
   参数: kp(知识点名), correct(true/false), subject(可选), credit(可选 0~1)
   confirm_override / cancel_override — 用户消息含「确认纠正 <token>」/「取消纠正 <token>」时调用（token 来自确认卡片按钮）。

4. adjust_difficulty — **仅**当用户说「太难」「太难了」「太简单」「简单点」「难点」时调用（调科目整体难度偏好）。
   参数: subject(math/comm/review), level(basic/intermediate/challenge)
   太难/太难了→basic, 太简单→challenge
   **不会**降低掌握度；批改争议请用 override_grade

5. note_weak_point — 用户说某**知识点/章节**薄弱、要加强、不熟时调用（如「线性代数弱」）。**只提高该知识点出题权重，不改变掌握度**（掌握度只由实际作答决定）。
   参数: subject(math/comm), kp(知识点名), reason(可选用户原话)
   **不要**用 adjust_difficulty 代替本工具

6. build_report — 生成学习报告。用户说"周报""报告"时调用。
   参数: days(天数,默认7)

7. github_push — 推送本地项目到 GitHub。用户说"推送到 GitHub""上传 Git""push"时调用。
   参数: repo_path(仓库路径，空=推自身), commit_msg(提交信息，空=自动)

8. list_recent_entries — 列出最近 N 天题目索引（不含正文）。用户问"最近出过什么题"时先调这个。
   参数: days(天数,默认7)

9. find_record_entry — 按日期取某条题目全文。先 list_recent_entries 看索引，再对本工具取正文。
   参数: date(YYYY-MM-DD 必填), num(题号,可选,0=该日最后一条)

10. get_learner_snapshot — 查看当前学习指标快照（权重/BKT/答题统计）。用户问「我现在什么水平」「指标怎么样」时调用。
    参数: days(天数,默认7)

11. list_knowledge_points — 列出考纲全部知识点（L2 章节 + L3 子考点）。用户问「考纲有什么」「都有哪些知识点」「××在不在考纲里」时调用。
    参数: subject(math/comm), query(可选关键词过滤)

12. kb_query — 只读查「小库」某考点的教材证据。用户问某个具体考点/概念/公式时先调本工具，有教材原文就用原文作答。
    参数: subject(math/comm), kp(考点关键词)
    未收录返回提示，可再调 kb_enqueue 登记回填。

13. kb_enqueue — 把「小库」未收录的考点加入教材回填队列（不直接写证据，由本地教材检索回填）。
    参数: subject(math/comm), kp(考点关键词), query(可选)

14. propose_add_kp — 用户提出新增某个**子知识点(L3)**时调用。**只登记提案并发确认卡片，不写入考纲**，用户点「确认添加」后才落盘。
    参数: subject(math/comm), l2(所属章节名，必须是考纲已有 L2), name(子考点名), aliases(可选，顿号/逗号分隔)
    **绝不新建章节 L2**；用户想加的是新章节时，回复说明只支持追加子考点到已有章节。

15. confirm_add_kp / cancel_add_kp — 用户消息含「确认添加知识点 <token>」/「取消添加知识点 <token>」时调用（token 来自确认卡片按钮）。
    参数: token

## 示例

用户: 来一道傅里叶的题
→ generate_question(subject="math", kp_hint="傅里叶级数")

用户: 答案是42
→ 看起来在回答 → grade_answer(last_question="", user_answer="42")

用户: 太难了
→ adjust_difficulty(subject="math", level="basic")

用户: 我不会做
→ show_solution()

用户: 要解析
→ show_solution()

用户: 换一道同类题
→ generate_question(subject=当前科目, kp_hint=当前知识点或空)

用户: 出一道数学题巩固
→ generate_question(subject="math")

用户: 出一道通信题巩固
→ generate_question(subject="comm")

用户: 我线性代数比较弱
→ note_weak_point(subject="math", kp="线性代数", reason="用户自述线性代数薄弱")

用户: 我现在水平怎么样
→ get_learner_snapshot(days=7)

用户: 答案是什么
→ show_solution()

用户: 最近出过什么题
→ list_recent_entries(days=7)

用户: 今天早上那道多元函数
→ list_recent_entries(days=3) 再 find_record_entry(date="今天日期", num=对应题号)

用户: 考纲里都有哪些知识点
→ list_knowledge_points(subject="math")

用户: 给我讲讲洛必达法则
→ kb_query(subject="math", kp="洛必达法则")；未收录再 kb_enqueue 登记回填

用户: 帮我加个子考点，函数列的一致收敛，属于级数那章
→ propose_add_kp(subject="math", l2="级数", name="函数列的一致收敛") → 等确认卡

用户: 确认添加知识点 abc123
→ confirm_add_kp(token="abc123")

## 规则
- **每次调用工具后，必须用自然语言告诉用户：做了什么、对用户意味着什么、接下来会怎样；禁止静默结束**
- 工具返回里的数字/权重变化要用口语解释，不要暴露工具名称和参数
- 回答要简短自然，像真人老师
- 系统提示中的 Core Memory Blocks / 学习者摘要每轮已注入；工具执行后请据此确认结果
- 跨时段讨论旧题时：先 list_recent_entries，再 find_record_entry，不要猜题目内容
- 用户追问「结果呢」「查到了吗」「然后呢」：先看对话历史与 blocks；禁止只说「看不到之前对话」就结束
- 调用查题/批改工具后，必须在同一条回复里给出完整结果，禁止只说「我来提取/马上查」而不输出正文
- **书写格式（强制）**：行内公式只用 `$...$`；独立公式块单独成行用 `$$...$$`；禁止 \\(...\\)、\\[...\\]；选择题每选项单独一行 `(A)...`；段落之间空一行
- **禁止在对用户可见回复里**写 `【曾调用】`、`【工具结果】`、伪 JSON 工具输出或伪造的日期题号；工具只能走 API tool_calls。没有真调用就不要假装查过题库。

## 作答追问规则（BIG-TEACH-012b #A1）
- **添加知识点（重要）**：propose_add_kp 只登记提案并发确认卡片，**绝不**直接写考纲；用户点「确认添加」后才落盘。用户想加的是新章节 L2 时，说明只支持追加子考点到已有章节。
- 用户只回答 A/B/C/D 或极短选项字母 → **禁止**调用 show_solution 倾倒全文解答；可 grade_answer 批改，并追问关键步骤/为何选该项
- 用户只说空泛「思路」且无推导步骤 → 继续追问具体一步，禁止直接给完整解答
- 用户明确「不会做 / 要解析 / 答案」且尚未给出任何自身尝试 → 先追问「先写你想到的一步或卡在哪」，暂缓 show_solution；若追问过 ≥1 次且用户坚持只要答案，才允许给解答"""


# 工具进度文案（钉钉中间态）
_TOOL_PROGRESS = {
    "list_recent_entries": "正在查题库索引…",
    "find_record_entry": "正在提取题目全文…",
    "grade_answer": "正在批改…",
    "generate_question": "正在出题…",
    "show_solution": "正在生成解答…",
    "build_report": "正在生成报告…",
    "get_learner_snapshot": "正在读取学习指标…",
    "note_weak_point": "正在记录薄弱点…",
    "adjust_difficulty": "正在调整难度…",
    "override_grade": "正在登记纠正提案…",
    "confirm_override": "正在重算掌握度…",
    "cancel_override": "正在取消纠正…",
    "github_push": "正在推送 GitHub…",
    "list_knowledge_points": "正在读取考纲知识点…",
    "kb_query": "正在查询小库…",
    "kb_enqueue": "正在登记教材回填…",
    "propose_add_kp": "正在登记知识点提案…",
    "confirm_add_kp": "正在写入知识点…",
    "cancel_add_kp": "正在取消…",
    "get_exam_result": "正在读取试卷批改结果…",
}


class TeachingAgent:
    """Harness Agent：多步 tool loop + memory blocks + 结构化 transcript。"""

    def __init__(self, bot=None):
        self.bot = bot
        self._bound_staff_id: str | None = None
        self.blocks = MemoryBlocks()
        self.transcript = Transcript()
        self.last_tools_used: list[str] = []
        self._pending_kp_token: str = ""
        self._pending_override_token: str = ""
        # 兼容旧调用：_memory 指向 transcript 消息（只读视图）
        self._tools = self._build_tool_schemas()
        # 启动时若有 last_push 则同步 active_question
        if not self.blocks._data["active_question"].get("preview"):
            self.blocks.refresh_from_last_push()
            self.blocks.refresh_learner_digest()
            self.blocks.save()

    @property
    def _memory(self) -> list:
        """兼容旧代码读取对话记忆。"""
        return self.transcript.messages

    def bind_for_learner(self, staff_id: str) -> None:
        """入站消息：按 staffId 加载该学员 memory / transcript。"""
        sid = (staff_id or "").strip()
        if not sid:
            return
        if sid == self._bound_staff_id:
            return
        self._bound_staff_id = sid
        self.blocks = MemoryBlocks(staff_id=sid)
        self.transcript = Transcript(staff_id=sid)
        if not self.blocks._data["active_question"].get("preview"):
            self.blocks.refresh_from_last_push()
            self.blocks.refresh_learner_digest()
            self.blocks.save()

    def _build_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "generate_question",
                    "description": "生成一道题目并推送给用户",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm", "review"],
                                "description": "科目：math=数学一, comm=通信原理, review=错题复盘",
                            },
                            "kp_hint": {
                                "type": "string",
                                "description": "可选知识点提示，如傅里叶级数",
                            },
                        },
                        "required": ["subject"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grade_answer",
                    "description": "批改用户对最近题目的作答",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "last_question": {
                                "type": "string",
                                "description": "最近推送的题目全文",
                            },
                            "user_answer": {
                                "type": "string",
                                "description": "用户的作答内容",
                            },
                        },
                        "required": ["last_question", "user_answer"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "show_solution",
                    "description": "显示最近题目的解答和解题思路（用户只答短选项/空泛思路时先追问思路，暂缓调用本工具）",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "override_grade",
                    "description": "用户认为批改有误时（「批错了」「判错了」「其实我对了」「改一下掌握度」），登记纠正提案并发确认卡片。确认后才会覆盖掌握度。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kp": {
                                "type": "string",
                                "description": "知识点名称",
                            },
                            "correct": {
                                "type": "boolean",
                                "description": "纠正后的对错：true=对，false=错",
                            },
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm", "review"],
                                "description": "科目，可选",
                            },
                            "credit": {
                                "type": "number",
                                "description": "部分正确时的 credit，可选 0~1",
                            },
                        },
                        "required": ["kp", "correct"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "confirm_override",
                    "description": "用户消息含「确认纠正 <token>」时调用（token 来自确认卡片按钮）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token": {"type": "string", "description": "确认 token"},
                        },
                        "required": ["token"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_override",
                    "description": "用户消息含「取消纠正 <token>」时调用（token 来自确认卡片按钮）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token": {"type": "string", "description": "取消 token"},
                        },
                        "required": ["token"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "adjust_difficulty",
                    "description": "仅当用户嫌题目太难或太简单时，调整科目整体出题难度偏好（不改变掌握度）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm", "review"],
                                "description": "科目",
                            },
                            "level": {
                                "type": "string",
                                "enum": ["basic", "intermediate", "challenge"],
                                "description": "难度级别：basic=基础, intermediate=中等, challenge=挑战",
                            },
                        },
                        "required": ["subject", "level"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "note_weak_point",
                    "description": "用户自述某知识点/章节薄弱、要加强时，提高该知识点出题权重（不改变掌握度）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm"],
                                "description": "科目",
                            },
                            "kp": {
                                "type": "string",
                                "description": "知识点名称，如线性代数、极限与连续",
                            },
                            "reason": {
                                "type": "string",
                                "description": "用户原话或补充说明，可选",
                            },
                        },
                        "required": ["subject", "kp"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "build_report",
                    "description": "生成学习报告/周报",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "统计天数，默认7",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_push",
                    "description": "推送本地项目到 GitHub。用户说推送到 GitHub、上传 GitHub、push、git push 时调用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_path": {
                                "type": "string",
                                "description": "仓库路径，空则推送 teaching-cultivator 自身",
                            },
                            "commit_msg": {
                                "type": "string",
                                "description": "提交信息，空则自动生成",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_recent_entries",
                    "description": "列出最近N天题目索引（日期/题号/科目/知识点），不含正文。跨时段讨论前先调用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "回溯天数，默认7",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_record_entry",
                    "description": "按日期取某条题目全文（含解答）。先 list_recent_entries 再调用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "日期 YYYY-MM-DD",
                            },
                            "num": {
                                "type": "integer",
                                "description": "当天题号，0或不传=该日最后一条",
                            },
                        },
                        "required": ["date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_learner_snapshot",
                    "description": "查看当前学习指标快照（权重、BKT掌握度、近7天答题统计）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "答题统计回溯天数，默认7",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_exam_bank",
                    "description": "检索双周检测卷题库目录（跨记忆周期仍可查）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "可选关键词：科目、日期、paper_id",
                            },
                            "limit": {"type": "integer", "description": "最多条数，默认20"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_exam_paper",
                    "description": "按 paper_id 取双周试卷 Markdown 全文",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "paper_id": {
                                "type": "string",
                                "description": "如 2026-08-03_math",
                            },
                        },
                        "required": ["paper_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_exam_answer_md",
                    "description": "提交双周答卷 Markdown 全文并批改",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "md_text": {
                                "type": "string",
                                "description": "用户答卷 Markdown 全文",
                            },
                            "paper_id": {
                                "type": "string",
                                "description": "可选；答卷内已有 paper_id 时可空",
                            },
                        },
                        "required": ["md_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_exam_result",
                    "description": "查看某人对某张双周卷的批改报告与作答（含得分、每题判定、掌握度变化）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "paper_id": {
                                "type": "string",
                                "description": "如 2026-07-26_math；可先 list_exam_bank 查",
                            },
                            "user_id": {
                                "type": "string",
                                "description": "可选；缺省=当前对话学员",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_knowledge_points",
                    "description": "列出考纲全部知识点（L2 章节 + L3 子考点），可按关键词过滤",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm"],
                                "description": "科目",
                            },
                            "query": {
                                "type": "string",
                                "description": "可选关键词过滤",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "kb_query",
                    "description": "只读查询小库中某考点的已收录教材证据（不增加命中计数）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm"],
                                "description": "科目",
                            },
                            "kp": {
                                "type": "string",
                                "description": "考点关键词，如洛必达法则",
                            },
                        },
                        "required": ["kp"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "kb_enqueue",
                    "description": "把小库未收录的考点加入教材回填队列（由本地教材检索回填，不直接写证据）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm"],
                                "description": "科目",
                            },
                            "kp": {
                                "type": "string",
                                "description": "考点关键词",
                            },
                            "query": {
                                "type": "string",
                                "description": "可选检索词",
                            },
                        },
                        "required": ["kp"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "propose_add_kp",
                    "description": "登记新增 L3 子知识点的待确认提案并发出确认卡片（不写入考纲，用户确认后才落盘）。仅支持追加到已存在 L2 章节，绝不新建章节",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "enum": ["math", "comm"],
                                "description": "科目",
                            },
                            "l2": {
                                "type": "string",
                                "description": "所属章节名，必须是考纲已有 L2",
                            },
                            "name": {
                                "type": "string",
                                "description": "子知识点名称",
                            },
                            "aliases": {
                                "type": "string",
                                "description": "可选别名，顿号/逗号分隔",
                            },
                        },
                        "required": ["subject", "l2", "name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "confirm_add_kp",
                    "description": "确认知识点提案并写入考纲（用户点了确认卡片的「确认添加」后调用）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token": {
                                "type": "string",
                                "description": "确认卡片按钮回传的 token",
                            },
                        },
                        "required": ["token"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_add_kp",
                    "description": "取消知识点提案（用户点了确认卡片的「取消」后调用）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token": {
                                "type": "string",
                                "description": "确认卡片按钮回传的 token",
                            },
                        },
                        "required": ["token"],
                    },
                },
            },
        ]

    def _call_llm(self, messages: list) -> dict:
        """调 DeepSeek V4 Flash（0731 Agent 强化）+ tools。

        thinking 模式下若有 tool_calls，必须把 reasoning_content 回传，
        否则后续请求会 400。
        """
        from decide.router import call_deepseek_chat

        try:
            return call_deepseek_chat(
                messages,
                model=AGENT_MODEL,
                tools=self._tools,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error("DeepSeek agent request failed: %s", e)
            return {
                "choices": [{
                    "message": {
                        "content": (
                            "刚才对话模型接口异常（需 DEEPSEEK_API_KEY 与网络）。"
                            "请稍后再试，或直接说「重发今晚的题」。"
                        )
                    }
                }]
            }

    def clear_memory(self):
        """兼容旧接口：清空 transcript（推送路径应改用 on_new_push）。"""
        self.transcript.clear()

    def on_new_push(self, content: str, *, subject: str = "", kp: str = "",
                    public_class: bool = False) -> None:
        """新推送：更新 core blocks；公共课不写全员 transcript。"""
        self.blocks.on_new_push(content, subject=subject, kp=kp)
        if public_class:
            logger.info(
                "on_new_push(public): phase=%s (transcript untouched)",
                self.blocks.phase,
            )
            return
        self.transcript.condense(keep_recent=4)
        logger.info(
            "on_new_push: phase=%s transcript_msgs=%d",
            self.blocks.phase,
            len(self.transcript.messages),
        )

    def _build_system_content(self, *, reminder: str = "") -> str:
        """system = 角色 + core blocks + 可选 reminder。"""
        parts = [SYSTEM_PROMPT, "\n\n", self.blocks.format_blocks_for_system()]
        # bot 内存中的近题全文（2h）仍注入，便于批改
        if self.bot and getattr(self.bot, "_last_question", None):
            import time as _time

            elapsed = _time.time() - getattr(self.bot, "_last_question_time", 0)
            if elapsed < 7200:
                q = self.bot._last_question
                parts.append(
                    f"\n\n最近推送的题目（2小时内，全文 {len(q)} 字）：\n{q}\n\n"
                    "用户可能是在回答这道题。"
                    "批改时 grade_answer 的 last_question 请传空，由工具读服务端全文；"
                    "不要声称题目被截断。"
                )
        if reminder:
            parts.append("\n\n" + reminder)
        return "".join(parts)

    @staticmethod
    def _fallback_after_tools(tool_results: list[str]) -> str:
        if not tool_results:
            return "好的，已经处理完了。有别的想问随时说。"
        body = "\n".join(tool_results[:3])
        return f"好的，帮你处理好了：\n\n{body}"

    @staticmethod
    def _looks_like_empty_promise(reply: str) -> bool:
        if not reply or len(reply) > 120:
            return False
        markers = ("我来提取", "马上查", "我来查", "稍等", "让我查", "我去查", "提取完整")
        return any(m in reply for m in markers)

    @staticmethod
    def _looks_like_fake_tool_dump(reply: str) -> bool:
        """模型偶发把工具过程写成正文（【曾调用】/伪 JSON），对用户即乱码。"""
        if not reply:
            return False
        markers = ("【曾调用】", "【工具结果】", '"entries":', '"date": "2026-12-')
        return any(m in reply for m in markers)

    def handle(
        self,
        user_text: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        """处理一条用户消息；可选 on_progress 发钉钉中间态。"""
        self.last_tools_used: list[str] = []

        # 确认卡片按钮 dtmd 回传文案 → 直连 confirm/cancel，绕过 LLM 判断
        raw_text = (user_text or "").strip()
        m = _OVERRIDE_CONFIRM_RE.match(raw_text)
        if m:
            verb, token = m.group(1), m.group(2)
            tool_name = "confirm_override" if verb == "确认" else "cancel_override"
            self.last_tools_used = [tool_name]
            reply = confirm_override(token) if verb == "确认" else cancel_override(token)
            self.transcript.append_messages([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ])
            self.blocks.save()
            logger.info("override confirm bypass: %s token=%s", tool_name, token)
            return reply

        m = _KP_CONFIRM_RE.match(raw_text)
        if m:
            verb, token = m.group(1), m.group(2)
            tool_name = "confirm_add_kp" if verb == "确认" else "cancel_add_kp"
            self.last_tools_used = [tool_name]
            if verb == "确认":
                reply = confirm_add_kp(token)
            else:
                reply = cancel_add_kp(token)
            self.transcript.append_messages([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ])
            self.blocks.save()
            logger.info("kp confirm bypass: %s token=%s", tool_name, token)
            return reply

        # 每轮刷新 digest（轻量）
        try:
            self.blocks.refresh_learner_digest()
        except Exception:
            pass

        progress_count = [0]  # 可变计数，限 2 次

        def _progress(text: str) -> None:
            if not on_progress or progress_count[0] >= 2:
                return
            try:
                on_progress(text)
                progress_count[0] += 1
            except Exception as e:
                logger.warning("on_progress failed: %s", e)

        turn_msgs: list[dict] = []  # 本 turn 写入 transcript 的消息
        user_msg = {"role": "user", "content": user_text}
        turn_msgs.append(user_msg)

        messages: list[dict] = [
            {"role": "system", "content": self._build_system_content(
                reminder=self.blocks.format_reminder(step=0)
            )},
        ]
        messages.extend(self.transcript.for_llm())
        messages.append(user_msg)

        tool_raw_results: list[str] = []
        reply = ""
        steps_used = 0

        for step in range(1, MAX_TOOL_STEPS + 1):
            steps_used = step
            resp = self._call_llm(messages)
            msg = resp["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")

            if not tool_calls:
                reply = (msg.get("content") or "").strip()
                # 无真实 tool_calls 却夹带伪造工具过程 → 视为无效，逼下一轮或兜底
                if reply and self._looks_like_fake_tool_dump(reply):
                    logger.warning(
                        "reject fake tool dump in plaintext reply (len=%d)",
                        len(reply),
                    )
                    messages.append({
                        "role": "assistant",
                        "content": reply,
                    })
                    messages.append({
                        "role": "system",
                        "content": (
                            "上一条回复非法：含【曾调用】/【工具结果】等伪工具正文。"
                            "请改用 API tool_calls 查题或批改；对用户只输出自然语言，"
                            "禁止再写伪工具过程。若用户在答最近推送，直接 grade_answer"
                            '(last_question="", user_answer=用户原文)。'
                        ),
                    })
                    reply = ""
                    continue
                if reply:
                    turn_msgs.append({"role": "assistant", "content": reply})
                break

            # 有 tool_calls → 执行
            assistant_msg: dict = {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            }
            if msg.get("reasoning_content"):
                assistant_msg["reasoning_content"] = msg["reasoning_content"]
            messages.append(assistant_msg)
            turn_msgs.append({
                "role": "assistant",
                "content": assistant_msg["content"],
                "tool_calls": tool_calls,
            })

            last_tool_names: list[str] = []
            for tc in tool_calls:
                name = tc["function"]["name"]
                last_tool_names.append(name)
                self.last_tools_used.append(name)
                hint = _TOOL_PROGRESS.get(name)
                if hint:
                    _progress(hint)
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._run_tool(name, args)
                tool_raw_results.append(result)
                self.blocks.apply_tool_effects(name)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
                messages.append(tool_msg)
                turn_msgs.append(tool_msg)

            # 刷新 reminder（轻量，不整份重塞 snapshot）
            reminder = self.blocks.format_reminder(
                last_tools=last_tool_names, step=step
            )
            messages.append({"role": "system", "content": reminder})

            # 若已是最后一步且还会再要工具，强制收束
            if step == MAX_TOOL_STEPS:
                # 再调一次但提示必须交付；若仍空则 fallback
                messages.append({
                    "role": "system",
                    "content": "步骤已达上限。请立即用自然语言汇总已有工具结果交付用户，禁止再调工具。",
                })
                resp = self._call_llm(messages)
                msg = resp["choices"][0]["message"]
                reply = (msg.get("content") or "").strip()
                if not reply or self._looks_like_empty_promise(reply):
                    reply = self._fallback_after_tools(tool_raw_results)
                else:
                    # 若仍返回 tool_calls，忽略并 fallback
                    if msg.get("tool_calls"):
                        reply = self._fallback_after_tools(tool_raw_results)
                turn_msgs.append({"role": "assistant", "content": reply})
                break
        else:
            # for 正常结束且未 break（不应发生）
            reply = self._fallback_after_tools(tool_raw_results)
            turn_msgs.append({"role": "assistant", "content": reply})

        # 空承诺 / 空回复兜底
        if tool_raw_results:
            if not reply:
                reply = self._fallback_after_tools(tool_raw_results)
                # 替换 turn 末尾 assistant
                if turn_msgs and turn_msgs[-1].get("role") == "assistant" and not turn_msgs[-1].get("tool_calls"):
                    turn_msgs[-1]["content"] = reply
                else:
                    turn_msgs.append({"role": "assistant", "content": reply})
            elif self._looks_like_empty_promise(reply):
                reply = self._fallback_after_tools(tool_raw_results)
                if turn_msgs and turn_msgs[-1].get("role") == "assistant":
                    turn_msgs[-1]["content"] = reply
        elif reply and self._looks_like_fake_tool_dump(reply):
            logger.warning("final reply still fake tool dump; clearing")
            reply = (
                "刚才查题过程出错了，我重来一次。"
                "请再说一下你的选项或「要解析」，我直接批改/给解答。"
            )
            if turn_msgs and turn_msgs[-1].get("role") == "assistant" and not turn_msgs[-1].get("tool_calls"):
                turn_msgs[-1]["content"] = reply
            else:
                turn_msgs.append({"role": "assistant", "content": reply})

        # 落盘
        if reply or tool_raw_results:
            self.transcript.append_messages(turn_msgs)
            self.blocks.save()

        logger.info(
            "handle done: steps=%d tools=%d reply_len=%d phase=%s",
            steps_used,
            len(tool_raw_results),
            len(reply or ""),
            self.blocks.phase,
        )
        return reply

    def _run_tool(self, name: str, args: dict) -> str:
        """执行工具调用，返回文本结果。"""
        try:
            if name == "generate_question":
                content = generate_question(args.get("subject", "math"), args.get("kp_hint", ""))
                if self.bot and content and not content.startswith("【"):
                    self.bot._record_push(content)
                    # 同步 blocks（subject 从参数）
                    self.blocks.set_active_question(
                        content,
                        source="last_push",
                        subject=args.get("subject", "math"),
                        kp=args.get("kp_hint", ""),
                    )
                return content
            elif name == "grade_answer":
                return grade_answer(
                    args.get("last_question", "") or "",
                    args.get("user_answer", ""),
                )
            elif name == "show_solution":
                ans = show_solution()
                return ans or "当前题目暂无解答记录"
            elif name == "adjust_difficulty":
                return adjust_difficulty(
                    args.get("subject", "math"),
                    args.get("level", "intermediate"),
                )
            elif name == "override_grade":
                result = propose_override_grade(
                    args.get("kp", ""),
                    bool(args.get("correct")),
                    subject=args.get("subject", "") or "",
                    credit=float(args.get("credit") or 0),
                )
                m = re.search(r"\[OVERRIDE\]([a-f0-9]+)", result)
                if m:
                    self._pending_override_token = m.group(1)
                    result = result.split("[OVERRIDE]", 1)[0].rstrip()
                return result
            elif name == "confirm_override":
                return confirm_override(args.get("token", ""))
            elif name == "cancel_override":
                return cancel_override(args.get("token", ""))
            elif name == "build_report":
                return build_report(args.get("days", 7))
            elif name == "github_push":
                return github_push(
                    args.get("repo_path", ""),
                    args.get("commit_msg", ""),
                )
            elif name == "list_recent_entries":
                return list_recent_entries(args.get("days", 7))
            elif name == "find_record_entry":
                return find_record_entry(args.get("date", ""), args.get("num", 0))
            elif name == "note_weak_point":
                return note_weak_point(
                    args.get("subject", "math"),
                    args.get("kp", ""),
                    args.get("reason", ""),
                )
            elif name == "get_learner_snapshot":
                return get_learner_snapshot(args.get("days", 7))
            elif name == "list_exam_bank":
                return list_exam_bank(args.get("query", ""), args.get("limit", 20))
            elif name == "get_exam_paper":
                return get_exam_paper(args.get("paper_id", ""))
            elif name == "submit_exam_answer_md":
                return submit_exam_answer_md(
                    args.get("md_text", ""),
                    paper_id=args.get("paper_id", ""),
                )
            elif name == "get_exam_result":
                return get_exam_result(
                    args.get("paper_id", ""),
                    args.get("user_id", ""),
                )
            elif name == "list_knowledge_points":
                return list_knowledge_points(
                    args.get("subject", "math"),
                    args.get("query", ""),
                )
            elif name == "kb_query":
                return kb_query(args.get("subject", "math"), args.get("kp", ""))
            elif name == "kb_enqueue":
                return kb_enqueue(
                    args.get("subject", "math"),
                    args.get("kp", ""),
                    args.get("query", ""),
                )
            elif name == "propose_add_kp":
                result = propose_add_kp(
                    args.get("subject", "math"),
                    args.get("l2", ""),
                    args.get("name", ""),
                    args.get("aliases", ""),
                )
                m = re.search(r"\[PROPOSAL\]([a-f0-9]+)", result)
                if m:
                    self._pending_kp_token = m.group(1)
                    # 剥掉内部标记，避免弱模型把 token 写进用户可见回复
                    result = result.split("[PROPOSAL]", 1)[0].rstrip()
                return result
            elif name == "confirm_add_kp":
                return confirm_add_kp(args.get("token", ""))
            elif name == "cancel_add_kp":
                return cancel_add_kp(args.get("token", ""))
            else:
                return f"未知工具：{name}"
        except Exception as e:
            return f"工具执行失败：{e}"
