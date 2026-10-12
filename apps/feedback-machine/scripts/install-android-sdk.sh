#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
mkdir -p "$SDK_ROOT/cmdline-tools"
if [[ ! -d "$SDK_ROOT/cmdline-tools/latest" ]]; then
  TMP="$(mktemp -d)"
  curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -o "$TMP/cmdline-tools.zip"
  unzip -q "$TMP/cmdline-tools.zip" -d "$TMP"
  mv "$TMP/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
  rm -rf "$TMP"
fi
# shellcheck source=android-env.sh
source "$ROOT/scripts/android-env.sh"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
echo "ANDROID_SDK_ROOT=$SDK_ROOT"
