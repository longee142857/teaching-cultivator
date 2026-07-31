"""模型选择器 — 按任务类型选模型与通道（DeepSeek 直连 / OpenRouter）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from config import (
    AGENT_MODEL,
    MODEL_FLASH,
    MODEL_PRO,
    REVIEWER_MODEL,
    SSL_VERIFY,
)

logger = logging.getLogger(__name__)

# DeepSeek thinking effort：官方仅 high|max
# https://api-docs.deepseek.com/guides/thinking_mode
REASONING_EFFORT_MAX = "max"
REASONING_EFFORT_DEFAULT = "high"

Provider = Literal["deepseek", "openrouter"]


@dataclass
class ModelConfig:
    model: str
    provider: Provider = "deepseek"
    thinking: bool = False  # DeepSeek reasoning 开关
    effort: str = REASONING_EFFORT_DEFAULT  # high | max（仅 thinking 时有效）


def select_model(task_type: str, difficulty: str = "intermediate") -> ModelConfig:
    """给定任务类型，返回 {model, provider, thinking, effort}。

    矩阵：
      author/grade/explain/generate → DeepSeek Pro + thinking max
      polish/orchestrate              → DeepSeek Flash（文案）
      review_item/verify_grade        → OpenRouter REVIEWER_MODEL（异厂）
      agent                           → OpenRouter AGENT_MODEL
    """
    _ = difficulty  # 保留签名兼容
    if task_type in ("grade", "generate", "explain", "author"):
        return ModelConfig(
            MODEL_PRO, provider="deepseek", thinking=True, effort=REASONING_EFFORT_MAX
        )
    if task_type in ("polish", "orchestrate"):
        return ModelConfig(
            MODEL_FLASH, provider="deepseek", thinking=False, effort=REASONING_EFFORT_DEFAULT
        )
    if task_type in ("review_item", "verify_grade"):
        return ModelConfig(
            REVIEWER_MODEL, provider="openrouter", thinking=False, effort=REASONING_EFFORT_DEFAULT
        )
    if task_type == "agent":
        return ModelConfig(
            AGENT_MODEL, provider="openrouter", thinking=False, effort=REASONING_EFFORT_DEFAULT
        )
    return ModelConfig(
        MODEL_FLASH, provider="deepseek", thinking=False, effort=REASONING_EFFORT_DEFAULT
    )


def _post_deepseek(payload: dict) -> dict:
    import requests
    from config import DEEPSEEK_API_BASE, DEEPSEEK_API_KEY

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未设置 DEEPSEEK_API_KEY")
    resp = requests.post(
        f"{DEEPSEEK_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json=payload,
        timeout=300,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def _post_openrouter(payload: dict, *, title: str = "teaching-cultivator") -> dict:
    import requests
    from config import OPENROUTER_API_KEY, OPENROUTER_BASE
    from decide.http_util import detect_proxies

    if not OPENROUTER_API_KEY:
        raise RuntimeError("未设置 OPENROUTER_API_KEY（Agent/审查与 X-digest 共用）")
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/longee142857/teaching-cultivator",
            "X-Title": title,
        },
        json=payload,
        proxies=detect_proxies(),
        timeout=300,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def _content_from_response(data: dict) -> str:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return msg.get("content") or ""


def call_llm(
    system: str,
    user: str,
    task_type: str,
    difficulty: str = "intermediate",
    *,
    reasoning_effort: str | None = None,
) -> str:
    """按 task_type 调 DeepSeek 或 OpenRouter，返回最终 content。

    review_item / verify_grade：OpenRouter 失败时回退 DeepSeek Flash（降级独立性，不阻断）。
    """
    cfg = select_model(task_type, difficulty)
    effort = reasoning_effort or cfg.effort

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "stream": False,
    }

    if cfg.provider == "deepseek":
        if cfg.thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = (
                effort if effort in ("high", "max") else REASONING_EFFORT_MAX
            )
        else:
            payload["thinking"] = {"type": "disabled"}
        logger.info(
            "call_llm task=%s provider=deepseek model=%s thinking=%s effort=%s",
            task_type,
            cfg.model,
            cfg.thinking,
            payload.get("reasoning_effort", "off"),
        )
        data = _post_deepseek(payload)
        return _content_from_response(data)

    # openrouter
    logger.info(
        "call_llm task=%s provider=openrouter model=%s",
        task_type,
        cfg.model,
    )
    try:
        data = _post_openrouter(payload, title=f"teaching-cultivator-{task_type}")
        return _content_from_response(data)
    except Exception as e:
        if task_type not in ("review_item", "verify_grade"):
            raise
        logger.warning(
            "OpenRouter %s failed (%s); fallback DeepSeek Flash",
            task_type,
            e,
        )
        fb = {
            "model": MODEL_FLASH,
            "messages": messages,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        data = _post_deepseek(fb)
        return _content_from_response(data)


def call_openrouter_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    tools: list | None = None,
    tool_choice: str | None = "auto",
    title: str = "teaching-cultivator-agent",
) -> dict:
    """OpenRouter chat（供 Agent 工具循环）；返回完整 API JSON。"""
    payload: dict = {
        "model": model or AGENT_MODEL,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    logger.info("call_openrouter_chat model=%s tools=%s", payload["model"], bool(tools))
    return _post_openrouter(payload, title=title)
