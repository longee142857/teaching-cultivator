# teaching-cultivator

Personal **adaptive exam cultivation** runtime: scheduled practice pushes, conversational tutoring agent, grading with mastery write-back, evidence-gated item authoring, weekly reports, and biweekly mock papers.

Primary channel: **DingTalk Stream** (WeCom retained as optional fallback).

This repository is intended as a **readable, runnable reference** of a vertical system that already survived real daily use — not a minimal chatbot demo.

## What it does

| Capability | Behavior |
|------------|----------|
| Cultivate loop | assess → decide → generate → quality gate → deliver → record |
| Dual subjects | Graduate math track + communications-style professional track |
| Mastery | Bayesian-style write-back + syllabus weights + recent-pick rotation |
| Evidence gate | Retrieval miss can **refuse to author** (`RAG_STRICT=1` by default) |
| Agent tools | New item / grade / solution / difficulty / weak-point notes / exams |
| Schedule | Morning/afternoon subject pushes, evening review, weekly report, optional digests |

## Architecture (high level)

```
main.py
  ├─ DingTalk Stream listener
  ├─ Scheduler → cultivate / review / report / optional digests
  └─ Agent (tool loop) ──┐
                         ▼
              cultivate / grade / orchestrate / quality_gate
                         │
         syllabus + weights + kb_cache + (optional) external RAG
```

Details for contributors working inside the tree: see `ARCHITECTURE.md` and `CLAUDE.md`.

## Requirements

- Python 3.10+ recommended
- Network access to your LLM provider and DingTalk (or WeCom) APIs
- Optional: an external knowledge-base helper for RAG backfill (`KB_PATH`, `KB_QUERY_HELPER`)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
```

## Quick start

1. Copy env template and fill secrets **locally only**:

```bash
cp .env.example .env
```

2. Seed runtime data (syllabus ships in-repo; copy example weights):

```bash
mkdir -p data
cp data/weights.example.json data/weights.json
```

3. Run:

```bash
python main.py
```

Windows helper scripts (paths are relative to the repo root):

```bat
watchdog.bat
setup_scheduler.bat
```

## Configuration

All credentials come from environment variables or `.env` (gitignored).

| Variable | Purpose |
|----------|---------|
| `DEEPSEEK_API_KEY` | Author / grade / explain / polish (DeepSeek) |
| `DINGTALK_CLIENT_ID` / `DINGTALK_CLIENT_SECRET` | DingTalk Stream app |
| `DINGTALK_GROUP_CONVERSATION_ID` | Optional fixed group for scheduled pushes |
| `OPENROUTER_API_KEY` | reviewer 异厂校验（Flash 回退） |
| `AGENT_MODEL` / `REVIEWER_MODEL` | Agent=DeepSeek Flash；reviewer=OpenRouter |
| `KB_CACHE_TOKEN` | Optional HTTP auth for `kb_cache_api` |
| `RAG_STRICT` | `1` (default) refuse author on weak retrieval; `0` debug |
| `KB_PATH` / `KB_QUERY_HELPER` / `KB_PYTHON` | Optional external RAG helper |
| `DAILY_RECORD_DIR` | Where monthly records are exported |

See `.env.example` for the full list.

**Never commit `.env`, API keys, conversation IDs, or answer logs.**

## Repository layout

```
main.py / cultivate.py / grade.py / orchestrate.py / quality_gate.py
agent/          conversational tool harness
decide/         LLM routing helpers
deliver/        DingTalk / WeCom / digests / media
learner/        syllabus, BKT-related state, RAG contract, ability cycle
prompts/        templates + format rules
data/           syllabus seeds + local runtime state (most runtime files gitignored)
scripts/        tests, warmers, ops helpers
```

## Privacy / public-release notes

- Secrets must live in `.env` or the process environment.
- Runtime learner state (`answer-log.jsonl`, `conversation_id.json`, `kb_cache/store.json`, …) is gitignored.
- Personal session notes under `logs/SESSION_*` are not part of the public tree.
- If you fork this history from an older snapshot, **rotate any keys that ever appeared in git**.

## Status

Actively used vertical system. APIs and prompt contracts evolve; treat `scripts/_test_*.py` as the living acceptance surface for recent gates.

## License

No license file is attached yet. All rights reserved by the author unless a license is added later. Ask before commercial reuse.
