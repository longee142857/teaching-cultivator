# Skill: cursor-cloud (bank-workshop isolated)

Lifecycle CLI for Cursor Cloud Agents used by the bank workshop.

## Commands
| cmd | API |
|-----|-----|
| `list` | GET `/v1/agents` |
| `get <id>` | GET `/v1/agents/{id}` |
| `launch` | POST `/v1/agents` (or resume→`send`) |
| `send <id>` | POST `/v1/agents/{id}/runs` (retry on 409 `agent_busy`) |
| `wait <id>` | poll GET `/v1/agents/{id}/runs/{runId}` every ~45s; timeout 45m → cancel |
| `archive <id>` | POST `/v1/agents/{id}/archive` |
| `me` | GET `/v1/me` |

## Create body (OpenAPI-aligned)
```json
{
  "prompt": { "text": "..." },
  "name": "bank-workshop-author-batch1",
  "model": { "id": "composer-2.5" },
  "repos": [{ "url": "https://github.com/longee142857/teaching-cultivator", "startingRef": "master" }],
  "autoCreatePR": true,
  "skipReviewerRequest": true
}
```

## State
Persists to `data/cloud-agents-state.json`: `id, name, role, created_at, last_run_id, pr_url, status` — never secrets.

## Safety
- Load key via `CURSOR_API_KEY` env, or `scripts/load_key.py` when present on operator host.
- Do not launch unless parent/operator requests it.

## Live status note
OpenAPI enums agent `status` as `ACTIVE|ARCHIVED`, but live `GET /v1/agents` also returns `IDLE`. Treat anything except `ARCHIVED` as resumable for same-name launch.

## Repo layout
In teaching-cultivator, run from repo root:
`python3 tool-scripts/tools/cursor-cloud/cloud_agent.py list`
