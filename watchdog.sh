#!/usr/bin/env bash
# Restart loop for main.py. Override PYTHON if needed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

echo "[$(date -Is)] watchdog start cwd=$ROOT"
while true; do
  echo "[$(date -Is)] starting main.py"
  "$PYTHON" main.py || true
  echo "[$(date -Is)] main.py exited; sleep 10"
  sleep 10
done
