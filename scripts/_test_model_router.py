# -*- coding: utf-8 -*-
"""Model matrix router unit tests (no live LLM)."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT_MODEL, MODEL_FLASH, MODEL_PRO, REVIEWER_MODEL
from decide.router import call_deepseek_chat, call_llm, select_model


def check(cond: bool, msg: str, fails: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        fails.append(msg)


def main() -> None:
    fails: list[str] = []

    print("\n=== select_model matrix ===")
    for t in ("author", "generate", "grade", "explain"):
        cfg = select_model(t)
        check(cfg.provider == "deepseek", f"{t} provider=deepseek", fails)
        check(cfg.model == MODEL_PRO, f"{t} model=pro", fails)
        check(cfg.thinking is True, f"{t} thinking on", fails)

    for t in ("polish", "orchestrate"):
        cfg = select_model(t)
        check(cfg.provider == "deepseek", f"{t} provider=deepseek", fails)
        check(cfg.model == MODEL_FLASH, f"{t} model=flash", fails)
        check(cfg.thinking is False, f"{t} thinking off", fails)

    for t in ("review_item", "verify_grade"):
        cfg = select_model(t)
        check(cfg.provider == "openrouter", f"{t} provider=openrouter", fails)
        check(cfg.model == REVIEWER_MODEL, f"{t} model=reviewer", fails)

    cfg_agent = select_model("agent")
    check(cfg_agent.provider == "deepseek", "agent provider=deepseek", fails)
    check(cfg_agent.model == AGENT_MODEL, "agent model=AGENT_MODEL", fails)
    check(cfg_agent.thinking is True, "agent thinking on", fails)
    check(cfg_agent.effort == "max", "agent effort=max", fails)

    print("\n=== call_llm deepseek author ===")
    with patch("decide.router._post_deepseek") as mock_ds:
        mock_ds.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        out = call_llm("sys", "usr", "author")
        check(out == "ok", "author content", fails)
        payload = mock_ds.call_args[0][0]
        check(payload["model"] == MODEL_PRO, "author payload model", fails)
        check(
            payload.get("thinking", {}).get("type") == "enabled",
            "author thinking enabled",
            fails,
        )
        check("reasoning_effort" in payload, "author has reasoning_effort", fails)

    print("\n=== call_llm polish flash ===")
    with patch("decide.router._post_deepseek") as mock_ds:
        mock_ds.return_value = {
            "choices": [{"message": {"content": "polished"}}]
        }
        out = call_llm("sys", "usr", "polish")
        check(out == "polished", "polish content", fails)
        payload = mock_ds.call_args[0][0]
        check(payload["model"] == MODEL_FLASH, "polish flash model", fails)
        check(
            payload.get("thinking", {}).get("type") == "disabled",
            "polish thinking off",
            fails,
        )

    print("\n=== call_llm review openrouter ===")
    with patch("decide.router._post_openrouter") as mock_or:
        mock_or.return_value = {
            "choices": [{"message": {"content": '{"decision":"accept"}'}}]
        }
        out = call_llm("sys", "usr", "review_item")
        check("accept" in out, "review or content", fails)
        payload = mock_or.call_args[0][0]
        check(payload["model"] == REVIEWER_MODEL, "review model", fails)
        check("thinking" not in payload, "review no thinking key", fails)

    print("\n=== review OR fallback to flash ===")
    with patch("decide.router._post_openrouter", side_effect=RuntimeError("or down")), \
         patch("decide.router._post_deepseek") as mock_ds:
        mock_ds.return_value = {
            "choices": [{"message": {"content": "fallback"}}]
        }
        out = call_llm("sys", "usr", "verify_grade")
        check(out == "fallback", "verify fallback content", fails)
        payload = mock_ds.call_args[0][0]
        check(payload["model"] == MODEL_FLASH, "fallback flash", fails)

    print("\n=== call_deepseek_chat agent ===")
    with patch("decide.router._post_deepseek") as mock_ds:
        mock_ds.return_value = {
            "choices": [{"message": {"content": "hi", "tool_calls": []}}]
        }
        data = call_deepseek_chat(
            [{"role": "user", "content": "hello"}],
            model=AGENT_MODEL,
            tools=[{"type": "function", "function": {"name": "x"}}],
        )
        check("choices" in data, "agent response shape", fails)
        payload = mock_ds.call_args[0][0]
        check(payload["model"] == AGENT_MODEL, "agent model in payload", fails)
        check(
            payload.get("thinking", {}).get("type") == "enabled",
            "agent thinking enabled",
            fails,
        )
        check(payload.get("reasoning_effort") == "max", "agent effort max", fails)
        check("tools" in payload, "agent has tools", fails)

    print("\n=== TeachingAgent._call_llm wiring ===")
    from agent.agent import TeachingAgent

    with patch("decide.router.call_deepseek_chat") as mock_chat:
        mock_chat.return_value = {
            "choices": [{"message": {"content": "wired"}}]
        }
        ag = TeachingAgent(bot=None)
        resp = ag._call_llm([{"role": "user", "content": "ping"}])
        check(
            resp["choices"][0]["message"]["content"] == "wired",
            "agent wired",
            fails,
        )
        kwargs = mock_chat.call_args.kwargs
        check(kwargs.get("model") == AGENT_MODEL, "agent uses AGENT_MODEL", fails)
        check(kwargs.get("tools") is not None, "agent passes tools", fails)

    print("\n" + "=" * 60)
    if fails:
        print(f"DONE with {len(fails)} FAIL(s)")
        sys.exit(1)
    print("ALL MODEL ROUTER TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
