"""题目机制（出题 + 审核）facade。

权威实现仍在仓根 cultivate_* / quality_gate；本包定义模块边界与稳定入口。
前端答题不经本包；本包只负责题库生产与质检。
"""
from __future__ import annotations

from typing import Any, Optional


def pregen_slot(subject_or_fill: str) -> Any:
    from cultivate_bank import run_pregen_slot

    return run_pregen_slot(subject_or_fill)


def pick_ready(
    subject: str,
    *,
    kp: str = "",
    technique: str = "",
    learner_id: Optional[str] = None,
) -> Any:
    from learner.item_bank import pick_for_push

    return pick_for_push(subject, kp=kp, technique=technique, learner_id=learner_id)


def judge_bank(*, max_items: int | None = None, use_llm: bool = True) -> Any:
    from cultivate_judge import run_judge_slot

    return run_judge_slot(max_items=max_items, use_llm=use_llm)


def rule_gate(draft: str, answer: str, *, item_form: str = "") -> list[str]:
    from quality_gate import check_draft_answer

    return check_draft_answer(draft, answer, item_form=item_form)


__all__ = ["pregen_slot", "pick_ready", "judge_bank", "rule_gate"]
