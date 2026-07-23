"""模型选择器 — 按任务类型和难度选模型"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from config import MODEL_FLASH, MODEL_PRO

logger = logging.getLogger(__name__)

# 出题/讲解/批改：最强档。官方 thinking effort 仅 high|max，max 为最强。
# https://api-docs.deepseek.com/guides/thinking_mode
REASONING_EFFORT_MAX = "max"
REASONING_EFFORT_DEFAULT = "high"


@dataclass
class ModelConfig:
    model: str
    thinking: bool   # pro 的 reasoning 开关
    effort: str = REASONING_EFFORT_DEFAULT  # high | max（仅 thinking 时有效）


def select_model(task_type: str, difficulty: str = "intermediate") -> ModelConfig:
    """给定任务类型和难度，返回 {model, thinking, effort}。

    出题 / 讲解 / 批改 / 润色：deepseek-v4-pro + thinking + max。
    """
    if task_type in ("grade", "generate", "explain", "author", "polish", "orchestrate"):
        return ModelConfig(MODEL_PRO, thinking=True, effort=REASONING_EFFORT_MAX)

    return ModelConfig(MODEL_FLASH, thinking=False, effort=REASONING_EFFORT_DEFAULT)


def call_llm(
    system: str,
    user: str,
    task_type: str,
    difficulty: str = "intermediate",
    *,
    reasoning_effort: str | None = None,
) -> str:
    """调 DeepSeek API，返回最终 content（thinking 开时仍只回传 content）。

    官方 thinking 写法（OpenAI 兼容裸 JSON）：
      model: deepseek-v4-pro
      thinking: {"type": "enabled"}
      reasoning_effort: "high" | "max"
    """
    import requests
    from config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE

    cfg = select_model(task_type, difficulty)
    effort = reasoning_effort or cfg.effort

    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    if cfg.thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = effort if effort in ("high", "max") else REASONING_EFFORT_MAX
    else:
        payload["thinking"] = {"type": "disabled"}

    logger.info(
        "call_llm task=%s model=%s thinking=%s effort=%s",
        task_type,
        cfg.model,
        cfg.thinking,
        payload.get("reasoning_effort", "off"),
    )

    resp = requests.post(
        f"{DEEPSEEK_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json=payload,
        timeout=300,
        verify=False,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    return msg.get("content") or ""
