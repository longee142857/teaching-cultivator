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
assess → decide → generate (author) → orchestrate/polish → quality_gate → deliver → record
                              ↑
                     rag_retrieve / kb_cache (evidence)
```

Grading updates mastery-related state and can adjust future selection weights.

## Agent path

Same authoring and grading tools as the scheduler where possible, plus solution / difficulty / exam helpers. Memory blocks keep phase, active item, and a short learner digest across turns.

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
