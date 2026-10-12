#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/node_modules/@capacitor/core/dist/capacitor.js"
DEST="$ROOT/www/js/capacitor.js"
if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC — run npm ci in apps/feedback-machine" >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
cp -f "$SRC" "$DEST"
echo "Copied Capacitor runtime -> www/js/capacitor.js"
