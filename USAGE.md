# Usage

Prefer the root [README.md](README.md). This file is a short operator checklist.

## 1. Secrets

```bash
cp .env.example .env
# edit .env — never commit it
```

Required for a live DingTalk bot:

- `DEEPSEEK_API_KEY` — author / grade / explain / polish
- `DINGTALK_CLIENT_ID`
- `DINGTALK_CLIENT_SECRET`
- `OPENROUTER_API_KEY` — chat Agent (Haiku)、题目/批改审查、可选 X digest（共用同一 key）

Optional: WeCom fallback via `WECOM_*`, RAG helper via `KB_*`.  
Model overrides: `AGENT_MODEL`, `REVIEWER_MODEL`, `DEEPSEEK_MODEL_PRO`, `DEEPSEEK_MODEL_FLASH`.

## 2. Seed data

```bash
cp data/weights.example.json data/weights.json
```

Syllabus files `data/syllabus_math.json` and `data/syllabus_comm.json` ship with the repo.

## 3. Run

```bash
python main.py
```

Or Windows:

```bat
watchdog.bat
```

## 4. Channels

- **Primary:** DingTalk Stream (`deliver/dingtalk_bot.py`)
- **Fallback:** WeCom bot / webhook (`deliver/wecom_bot.py`, `deliver/bridge.py`)
- Scheduled pushes and conversational replies share the same cultivation / quality-gate path.

## 5. Smoke checks

```bash
python scripts/dry_prompt.py
python scripts/_test_model_router.py
python scripts/_test_rag_retrieve.py
python scripts/_test_l3_gate.py
```

Some tests skip when optional external KB helpers are unset.
