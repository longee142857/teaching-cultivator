"""Ability goal 选取 + 轮转 + item_form 映射（BIG-TEACH-011d）

AbilityGoal ∈ {recognize, compute, construct, transfer, diagnose}
状态机依据当前 L2/L3 BKT 信号决定最适合的能力目标。

用法:
    from learner.ability_cycle import decide_ability
    goal = decide_ability("math", "push", is_mastered=False, ...)
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from config import DATA_DIR

RECENT_ABILITY_PATH = os.path.join(DATA_DIR, "recent_ability_picks.json")
ROTATE_N = 3
ROTATE_PENALTY = 0.05

ABILITY_GOALS = ("recognize", "compute", "construct", "transfer", "diagnose")

# ability_goal → 默认 item_form
ITEM_FORM_MAP: dict[str, str] = {
    "recognize": "mcq",
    "diagnose": "mcq",
    "compute": "blank",
    "construct": "proof_outline",
    # transfer 继承上次 form，见 ability_to_item_form()
}


# ── Recent picks 持久化 ──


def _load_recent_picks() -> dict[str, list[str]]:
    try:
        if os.path.isfile(RECENT_ABILITY_PATH):
            with open(RECENT_ABILITY_PATH, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_recent_picks(data: dict[str, list[str]]) -> None:
    try:
        os.makedirs(os.path.dirname(RECENT_ABILITY_PATH) or ".", exist_ok=True)
        with open(RECENT_ABILITY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        pass


def append_recent_ability(subject: str, ability: str, *, maxlen: int = 6) -> None:
    if ability not in ABILITY_GOALS:
        return
    data = _load_recent_picks()
    picks = [p for p in (data.get(subject) or []) if isinstance(p, str)]
    picks = [ability] + [p for p in picks if p != ability]
    data[subject] = picks[:maxlen]
    _save_recent_picks(data)


def load_recent_abilities(subject: str) -> list[str]:
    data = _load_recent_picks()
    return [p for p in (data.get(subject) or []) if isinstance(p, str)]


def _apply_anti_repeat(subject: str, scores: dict[str, float]) -> dict[str, float]:
    """近 ROTATE_N 次同 ability ×ROTATE_PENALTY 降权。"""
    recent = load_recent_abilities(subject)[:ROTATE_N]
    out = dict(scores)
    for ability in recent:
        if ability in out:
            out[ability] = out[ability] * ROTATE_PENALTY
    return out


# ── 状态机 ──


def decide_ability(
    subject: str,
    intervention_type: str,
    *,
    is_mastered: bool = False,
    opportunity_count: int = 0,
    recent_correct: Optional[bool] = None,
    consecutive_failures: int = 0,
    is_due: bool = False,
    mastery: float = 0.0,
) -> str:
    """根据学习者状态 + 干预类型选择 ability_goal。

    States:
      cold (opp=0)         → recognize
      after_wrong/review   → diagnose
      near_mastery         → construct / transfer
      mastered+due         → recognize 轻测
      mastered (stable)    → transfer
      learning (default)   → 加权选，降权近期连续项
    """
    # after_wrong / review → diagnose
    if intervention_type == "review" or (recent_correct is False):
        return "diagnose"

    # cold / opp=0 / explain → recognize
    if opportunity_count == 0 or intervention_type == "explain":
        return "recognize"

    # 已掌握 + 到期 → recognize 轻测
    if is_mastered and is_due:
        return "recognize" if mastery < 0.9 else "transfer"

    # 已掌握（稳）→ transfer
    if is_mastered:
        return "transfer"

    # 到期复查（未掌握）→ construct
    if is_due:
        return "construct"

    # learning 阶段：加权选，降权近期连续项
    base_scores: dict[str, float] = {
        "recognize": 0.3,
        "compute": 1.0,
        "construct": 0.3,
        "transfer": 0.1,
        "diagnose": 0.1,
    }
    if mastery < 0.3:
        base_scores["recognize"] = 1.0
        base_scores["compute"] = 0.8
    elif mastery >= 0.7:
        base_scores["construct"] = 1.0
        base_scores["transfer"] = 0.7
        base_scores["compute"] = 0.5

    adjusted = _apply_anti_repeat(subject, base_scores)
    return max(adjusted, key=adjusted.get)  # type: ignore[return-value]


# ── item_form 映射 ──


def ability_to_item_form(ability_goal: str, last_form: str = "") -> str:
    """ability_goal → item_form。transfer 继承上次 form。"""
    if ability_goal == "transfer" and last_form in ("mcq", "blank", "proof_outline"):
        return last_form
    return ITEM_FORM_MAP.get(ability_goal, "mcq")


def encode_ability_reason(ability_goal: str) -> str:
    """生成 [ability=xxx] 标记，与 [l3=...] 并存。"""
    return f"[ability={ability_goal}]"


def parse_ability_from_reason(reason: str) -> str | None:
    """从 reason 提取 [ability=xxx]。"""
    m = re.search(r'\[ability=([^\]]+)\]', reason or "")
    return m.group(1).strip() if m else None


def _load_last_push_item_form() -> str:
    """从 last_push.json 读上次 item_form（供 transfer 继承）。"""
    last_push_path = os.path.join(DATA_DIR, "last_push.json")
    try:
        if os.path.isfile(last_push_path):
            with open(last_push_path, encoding="utf-8") as f:
                data = json.load(f)
            return str(data.get("item_form", "") or "")
    except (OSError, json.JSONDecodeError):
        pass
    return ""
