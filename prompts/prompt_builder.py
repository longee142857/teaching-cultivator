"""PromptBuilder — 模板加载、占位符渲染、上下文组装。

Usage:
    builder = PromptBuilder()
    system, user = builder.build(
        subject_cn="数学一", kp="极限", difficulty_cn="基础",
        action_cn="出题", reason="极限: 掌握度45%",
        decision_type="push", topic_desc="数学一考研",
        mastery=0.45, opportunity_count=3, consecutive_failures=0,
        ref_entry=ref_dict, rag_items=[...],
    )
"""
from __future__ import annotations
import os
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
FORMAT_RULES_PATH = Path(__file__).parent / "format_rules.md"


def load_format_rules(item_form: str = "mcq") -> str:
    """Shared writing-format rules; MCQ-only bullets omitted for blank/proof."""
    try:
        text = FORMAT_RULES_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "## 书写格式\n"
            "- 行内公式只用 $...$，禁止 \\(...\\)\n"
            "- 块公式单独成行用 $$...$$\n"
            "- 选择题每选项一行：(A) ...\n"
        )
    if item_form in ("blank", "proof_outline"):
        # 去掉「选择题 / 小题」整节（到下一个 ### 为止）
        lines = text.splitlines()
        out: list[str] = []
        skip = False
        for line in lines:
            if line.startswith("### 选择题"):
                skip = True
                continue
            if skip and line.startswith("### "):
                skip = False
            if not skip:
                out.append(line)
        return "\n".join(out).strip()
    return text


class PromptBuilder:
    """Loads prompts/templates/{type}.md, fills placeholders, returns (system, user)."""

    def __init__(self, template_dir: str | os.PathLike | None = None):
        self.template_dir = Path(template_dir or TEMPLATE_DIR)
        self._cache: dict[str, tuple[str, str]] = {}

    # ── 模板加载 ──

    def _load_template(self, decision_type: str) -> tuple[str, str]:
        """Load system+user from template file. Returns (system, user)."""
        cached = self._cache.get(decision_type)
        if cached:
            return cached

        tpl_path = self.template_dir / f"{decision_type}.md"
        if not tpl_path.is_file():
            raise FileNotFoundError(
                f"Template not found: {tpl_path} "
                f"(expected for decision type '{decision_type}')"
            )

        content = tpl_path.read_text(encoding="utf-8")

        # Split on first "\n---\n" (system / user separator)
        sep = "\n---\n"
        if sep not in content:
            raise ValueError(
                f"Template {tpl_path} must contain '{sep}' to separate system/user"
            )
        system_raw, user_raw = content.split(sep, 1)

        system = _strip_heading(system_raw, "# System")
        user = _strip_heading(user_raw, "# User")

        self._cache[decision_type] = (system, user)
        return system, user

    # ── 可选块格式化 ──

    @staticmethod
    def _format_ref_block(ref_entry: dict | None) -> str:
        """Format YAML reference question as an anchor block."""
        if not ref_entry:
            return ""
        q = ref_entry.get("question", "")
        src = ref_entry.get("source", {})
        if isinstance(src, dict):
            src_str = f"{src.get('year', '')}年{src.get('subject', '')}"
        else:
            src_str = str(src)
        kp_list = "、".join(ref_entry.get("kp", []))
        return (
            f"\n## 真题锚点\n"
            f"参考真题（{src_str}，知识点：{kp_list}）：\n"
            f"{q[:600]}\n"
            f"请参考上述真题的题型和难度，出一道同知识点、同水平的变式题。"
        )

    @staticmethod
    def _format_rag_block(rag_items: list[dict]) -> str:
        """Format RAG results as an auxiliary context block."""
        if not rag_items:
            return ""
        lines = ["\n## 考点知识辅助（云端小库/教材摘录）"]
        for item in rag_items:
            src = item.get("source", "?")
            page = item.get("page") or ""
            page_s = f" p.{page}" if page else ""
            text = item.get("text", "")[:300]
            lines.append(f"- 来自《{src}》{page_s}：{text}")
        return "\n".join(lines)

    @staticmethod
    def _format_iter_notes(notes: str) -> str:
        """Wrap iteration notes if non-empty."""
        return f"\n- 备注：{notes}" if notes else ""

    @staticmethod
    def _format_mastery(val: float) -> str:
        pct = max(0.0, min(1.0, val)) * 100
        return f"{pct:.0f}%"

    @staticmethod
    def build_strategy_hint(
        mastery: float,
        consecutive_failures: int,
        opportunity_count: int,
    ) -> str:
        """BKT 数字 → 一条自然语言出题策略（多条件取最严重）。"""
        if consecutive_failures >= 2:
            return (
                "该生该知识点连续错误，请降低题目复杂度，拆成小步骤，"
                "优先考察基础概念"
            )
        if mastery < 0.3:
            return "该生对该知识点几乎未掌握，请从最基础的定义和公式出发出题"
        if mastery >= 0.8:
            return "该生已熟练掌握该知识点，可以出综合题，跨知识点联系"
        if opportunity_count <= 1:
            return "该知识点首次练习，请出概念判断或简单计算题"
        return ""

    @staticmethod
    def _format_strategy_hint(hint: str) -> str:
        return f"\n\n## 出题策略\n{hint}" if hint else ""

    @staticmethod
    def _format_last_error(last_error: str) -> str:
        if not last_error:
            return ""
        return f"\n## 上次错题\n{last_error}\n"

    @staticmethod
    def _format_item_form_constraint(item_form: str) -> str:
        """System-level instruction: required output format per item_form."""
        if item_form == "blank":
            return (
                "\n本题题型要求：填空题（填写关键步骤或最终结果）。"
                "请在题目中使用下划线标记空位。禁止出选择题，禁止改成单选格式。"
            )
        if item_form == "proof_outline":
            return (
                "\n本题题型要求：证明/推导题。"
                "给出明确的命题或待推导结论，用户需写出完整证明或推导过程。"
                "禁止出选择题，禁止改成单选格式。"
            )
        # mcq default
        return (
            "\n本题题型要求：选择题。"
            "确保各选项互不相同，单选题必须恰有一解。"
            "出题前在心里验算各选项；多解必须改选项，禁止把多解题硬标成单选。"
        )

    @staticmethod
    def _format_item_form_user_constraint(item_form: str) -> str:
        """User-level instruction: what to produce for the given item_form.

        Replaces the hardcoded '单选恰一解' / '正确选项' in user sections.
        """
        if item_form == "blank":
            return "填空题，用户需填写关键步骤/最终结果，不要出选择题"
        if item_form == "proof_outline":
            return "证明/推导题，用户需写出完整证明或推导过程，不要出选择题"
        return "单选题须恰有一解（先验算再写选项），答案写正确选项字母 + 解析"

    # ── 主入口 ──

    def build(
        self,
        *,
        subject_cn: str,
        kp: str,
        difficulty_cn: str,
        action_cn: str,
        reason: str,
        decision_type: str,
        topic_desc: str,
        mastery: float = 0.0,
        opportunity_count: int = 0,
        consecutive_failures: int = 0,
        ref_entry: dict | None = None,
        rag_items: list[dict] | None = None,
        iteration_notes: str = "",
        exam_style_pct: int = 70,
        theory_extension_pct: int = 30,
        last_error: str = "",
        item_form: str = "mcq",
    ) -> tuple[str, str]:
        """Assemble system + user prompts from templates and context."""
        system_tpl, user_tpl = self._load_template(decision_type)

        strategy_hint = self.build_strategy_hint(
            mastery, consecutive_failures, opportunity_count
        )

        ref_block = self._format_ref_block(ref_entry)
        rag_block = self._format_rag_block(rag_items or [])
        iter_notes = self._format_iter_notes(iteration_notes)

        vals = {
            "topic_desc": topic_desc,
            "subject": subject_cn,
            "kp": kp,
            "difficulty": difficulty_cn,
            "action": action_cn,
            "reason": reason,
            "ref_block": ref_block,
            "rag_hints": rag_block,
            "mastery": self._format_mastery(mastery),
            "opportunity_count": str(opportunity_count),
            "consecutive_failures": str(consecutive_failures),
            "iteration_notes": iter_notes,
            "exam_style_pct": str(exam_style_pct),
            "theory_extension_pct": str(theory_extension_pct),
            "strategy_hint": self._format_strategy_hint(strategy_hint),
            "last_error": self._format_last_error(last_error),
            "format_rules": load_format_rules(item_form),
            "item_form_constraint": self._format_item_form_constraint(item_form),
            "item_form_user_constraint": self._format_item_form_user_constraint(item_form),
        }

        system = system_tpl
        user = user_tpl
        for key, val in vals.items():
            placeholder = "{{" + key + "}}"
            if placeholder in system:
                system = system.replace(placeholder, val)
            if placeholder in user:
                user = user.replace(placeholder, val)

        # 未使用占位符时去掉，避免模板残留
        for placeholder in (
            "{{strategy_hint}}", "{{last_error}}",
            "{{item_form_constraint}}", "{{item_form_user_constraint}}",
        ):
            system = system.replace(placeholder, "")
            user = user.replace(placeholder, "")

        return system, user

    def build_polish(self, *, draft_body: str, answer_body: str) -> tuple[str, str]:
        """第二阶段：把已验算草稿整理成推送正文。"""
        system_tpl, user_tpl = self._load_template("polish")
        vals = {
            "draft_body": (draft_body or "").strip() or "（草稿为空）",
            "answer_body": (answer_body or "").strip() or "（无答案）",
            "format_rules": load_format_rules(),
        }
        system, user = system_tpl, user_tpl
        for key, val in vals.items():
            placeholder = "{{" + key + "}}"
            system = system.replace(placeholder, val)
            user = user.replace(placeholder, val)
        return system, user

    def build_orchestrate(
        self,
        *,
        draft_body: str,
        answer_body: str,
        memory_digest: str = "",
        subject: str = "",
        kp: str = "",
        source: str = "schedule",
    ) -> tuple[str, str]:
        """编排层：带会话摘要的发送文案（Phase C）。"""
        system_tpl, user_tpl = self._load_template("orchestrate")
        vals = {
            "draft_body": (draft_body or "").strip() or "（草稿为空）",
            "answer_body": (answer_body or "").strip() or "（无答案）",
            "memory_digest": (memory_digest or "").strip() or "（无会话摘要）",
            "subject": subject or "",
            "kp": kp or "",
            "source": source or "schedule",
            "format_rules": load_format_rules(),
        }
        system, user = system_tpl, user_tpl
        for key, val in vals.items():
            placeholder = "{{" + key + "}}"
            system = system.replace(placeholder, val)
            user = user.replace(placeholder, val)
        return system, user


def _strip_heading(text: str, heading: str) -> str:
    """Remove a leading heading line if present."""
    for variant in (heading, heading.lower(), heading.lstrip("#").strip()):
        if text.startswith(variant + "\n"):
            text = text[len(variant):].strip()
            break
    return text.strip()
