#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f scripts/android-env.sh ]]; then
  # shellcheck source=android-env.sh
  source scripts/android-env.sh
fi
npm ci
bash scripts/copy-capacitor-runtime.sh
npx cap sync android
cd android
chmod +x gradlew 2>/dev/null || true
./gradlew assembleDebug --no-daemon
APK="app/build/outputs/apk/debug/app-debug.apk"
if [[ -f "$APK" ]]; then
  mkdir -p "$ROOT/artifacts"
  cp -f "$APK" "$ROOT/artifacts/feedback-machine-debug.apk"
  echo "Built: $ROOT/android/$APK"
  echo "Copied: $ROOT/artifacts/feedback-machine-debug.apk"
  echo "Local copy only. Do not commit the APK; CI uploads it as an artifact."
fi
