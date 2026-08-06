# Architecture

## Runtime

```
watchdog (optional)
  └─ main.py
       ├─ DingTalk Stream bot
       │    ├─ inbound messages → Agent
       │    └─ outbound push / cards / media
       ├─ scheduler thread
       │    └─ cultivate / review / weekly report / optional digests
       └─ optional kb_cache HTTP (:8765, token via env)
```

## Cultivate path

```
assess → decide → author → rule_gate → review_item → polish/orchestrate → deliver → record
                              ↑
                     rag_retrieve / kb_cache (evidence)
```

Grading: `grade` → `verify_grade` → apply|pending → mastery write-back when applied.

## Model matrix

| Role | Default model | Channel |
|------|---------------|---------|
| Agent (chat / tools) | `deepseek-v4-flash` + thinking max | DeepSeek direct (0731 agentic refresh) |
| author / grade / explain | `deepseek-v4-pro` + thinking | DeepSeek direct |
| review_item / verify_grade | `qwen/qwen3.6-plus` | OpenRouter (Flash fallback on OR failure) |
| polish / orchestrate | `deepseek-v4-flash` | DeepSeek direct |

Override via env: `AGENT_MODEL`, `AGENT_THINKING`, `AGENT_REASONING_EFFORT`, `REVIEWER_MODEL`, `DEEPSEEK_MODEL_*`.

## Agent path

Same authoring and grading tools as the scheduler where possible, plus solution / difficulty / exam helpers. Memory blocks keep phase, active item, and a short learner digest across turns. The Agent host is DeepSeek V4 Flash (post-0731); tool backends still call Pro for author/grade/explain.

## Channels

| Channel | Module | Role |
|---------|--------|------|
| DingTalk Stream | `deliver/dingtalk_bot.py` | Primary interactive + push |
| WeCom | `deliver/wecom_bot.py` | Optional fallback |
| Bridge | `deliver/bridge.py` / `push_hub.py` | Unified push entry |

## Design invariants

1. Evidence gate before author when `RAG_STRICT=1`.
2. Mastery keys stay normalized to syllabus grain.
3. Delivery constraints of the IM client are part of the product (math rendering, cards, group vs DM).
4. Content supply may be external; this repo is the **runtime**.
5. Critique roles (`review_item` / `verify_grade`) stay cross-provider from author/grade when OpenRouter is available.
