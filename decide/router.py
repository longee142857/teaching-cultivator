"""模型选择器 — 按任务类型选模型与通道（DeepSeek / DashScope / 可选 OpenRouter）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from config import (
    AGENT_MODEL,
    AGENT_REASONING_EFFORT,
    AGENT_THINKING,
    MODEL_FLASH,
    MODEL_PRO,
    REVIEWER_MODEL,
    REVIEWER_PROVIDER,
    SSL_VERIFY,
)

logger = logging.getLogger(__name__)

# DeepSeek thinking effort：官方仅 high|max
# https://api-docs.deepseek.com/guides/thinking_mode
REASONING_EFFORT_MAX = "max"
REASONING_EFFORT_DEFAULT = "high"

Provider = Literal["deepseek", "dashscope", "openrouter"]


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
      review_item/verify_grade        → REVIEWER_PROVIDER（默认 dashscope/qwen-plus）
      agent                           → DeepSeek Flash + thinking max
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
        prov: Provider = "dashscope"
        if REVIEWER_PROVIDER in ("dashscope", "openrouter", "deepseek"):
            prov = REVIEWER_PROVIDER  # type: ignore[assignment]
        return ModelConfig(
            REVIEWER_MODEL, provider=prov, thinking=False, effort=REASONING_EFFORT_DEFAULT
        )
    if task_type == "agent":
        effort = (
            AGENT_REASONING_EFFORT
            if AGENT_REASONING_EFFORT in ("high", "max")
            else REASONING_EFFORT_MAX
        )
        return ModelConfig(
            AGENT_MODEL or MODEL_FLASH,
            provider="deepseek",
            thinking=AGENT_THINKING,
            effort=effort,
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


def _post_dashscope(payload: dict) -> dict:
    """阿里云百炼 OpenAI 兼容接口（北京，直连，不走本地代理）。"""
    import requests
    from config import DASHSCOPE_API_BASE, DASHSCOPE_API_KEY

    if not DASHSCOPE_API_KEY:
        raise RuntimeError("未设置 DASHSCOPE_API_KEY（百炼控制台 API-KEY）")
    base = DASHSCOPE_API_BASE.rstrip("/")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
        verify=SSL_VERIFY,
        # 明确直连：不使用 detect_proxies / 环境代理翻墙
        proxies={"http": None, "https": None},
    )
    resp.raise_for_status()
    return resp.json()


def _post_openrouter(payload: dict, *, title: str = "teaching-cultivator") -> dict:
    import requests
    from config import OPENROUTER_API_KEY, OPENROUTER_BASE
    from decide.http_util import detect_proxies

    if not OPENROUTER_API_KEY:
        raise RuntimeError("未设置 OPENROUTER_API_KEY")
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


def _fallback_deepseek_flash(messages: list[dict], task_type: str, err: Exception) -> str:
    logger.warning(
        "%s failed (%s); fallback DeepSeek Flash",
        task_type,
        err,
    )
    fb = {
        "model": MODEL_FLASH,
        "messages": messages,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    data = _post_deepseek(fb)
    return _content_from_response(data)


def call_llm(
    system: str,
    user: str,
    task_type: str,
    difficulty: str = "intermediate",
    *,
    reasoning_effort: str | None = None,
) -> str:
    """按 task_type 调模型，返回最终 content。

    review_item / verify_grade：DashScope/OpenRouter 失败时回退 DeepSeek Flash（不阻断）。
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

    if cfg.provider == "dashscope":
        logger.info(
            "call_llm task=%s provider=dashscope model=%s",
            task_type,
            cfg.model,
        )
        try:
            data = _post_dashscope(payload)
            return _content_from_response(data)
        except Exception as e:
            if task_type not in ("review_item", "verify_grade"):
                raise
            return _fallback_deepseek_flash(messages, task_type, e)

    # openrouter（可选遗留）
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
        return _fallback_deepseek_flash(messages, task_type, e)


def call_openrouter_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    tools: list | None = None,
    tool_choice: str | None = "auto",
    title: str = "teaching-cultivator-agent",
) -> dict:
    """OpenRouter chat（遗留/可选）；返回完整 API JSON。"""
    payload: dict = {
        "model": model or REVIEWER_MODEL,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    logger.info("call_openrouter_chat model=%s tools=%s", payload["model"], bool(tools))
    return _post_openrouter(payload, title=title)


def call_deepseek_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    tools: list | None = None,
    tool_choice: str | None = "auto",
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    """DeepSeek chat（Agent 工具循环）；返回完整 API JSON。

    thinking 模式下若有 tool_calls，调用方须把 reasoning_content 回传。
    """
    use_thinking = AGENT_THINKING if thinking is None else thinking
    effort = reasoning_effort or AGENT_REASONING_EFFORT
    if effort not in ("high", "max"):
        effort = REASONING_EFFORT_MAX
    payload: dict = {
        "model": model or AGENT_MODEL or MODEL_FLASH,
        "messages": messages,
        "stream": False,
    }
    if use_thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = effort
    else:
        payload["thinking"] = {"type": "disabled"}
    if tools is not None:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    logger.info(
        "call_deepseek_chat model=%s tools=%s thinking=%s effort=%s",
        payload["model"],
        bool(tools),
        use_thinking,
        payload.get("reasoning_effort", "off"),
    )
    return _post_deepseek(payload)
