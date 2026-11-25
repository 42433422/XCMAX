#!/usr/bin/env bash
# Android 模拟器短测：debug APK 安装、冷启动、进程存活及截图。
# 不代表物理设备、签名候选、干净安装或商业交付验收。
# 由 ci-mobile-android-smoke.yml 在 emulator-runner 内调用；cwd = FHD/mobile-flutter-poc。
set -euo pipefail

APP_PACKAGE="${APP_PACKAGE:?APP_PACKAGE must be set}"
APK=build/app/outputs/flutter-apk/app-debug.apk
SCREEN=/tmp/android-smoke-screen.png
rm -f "$SCREEN"
if [ ! -s "$APK" ]; then
  echo "::error::debug APK missing or empty after build"
  exit 1
fi

echo "evidence_kind=android_emulator_debug_smoke_not_physical_acceptance"
source_sha=$(git rev-parse HEAD)
if [ -n "${GITHUB_SHA:-}" ] && [ "$source_sha" != "$GITHUB_SHA" ]; then
  echo "::error::checked-out source SHA differs from workflow SHA"
  exit 1
fi
printf 'source_sha=%s\n' "$source_sha"
printf 'apk_sha256=%s\n' "$(sha256sum "$APK" | cut -d ' ' -f 1)"
printf 'run_id=%s\nrun_attempt=%s\n' "${GITHUB_RUN_ID:-unknown}" "${GITHUB_RUN_ATTEMPT:-unknown}"
printf 'android_version=%s\nandroid_model=%s\n' "$(adb shell getprop ro.build.version.release | tr -d '\r')" "$(adb shell getprop ro.product.model | tr -d '\r')"
printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "installing $APK"
adb install -r -g "$APK"
# A pre-existing process must not satisfy this cold-start assertion.
adb shell am force-stop "$APP_PACKAGE"
if [ -n "$(adb shell pidof "$APP_PACKAGE" || true)" ]; then
  echo "::error::app process still alive after force-stop"
  exit 1
fi
adb shell monkey -p "$APP_PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 15

if [ -z "$(adb shell pidof "$APP_PACKAGE" || true)" ]; then
  echo "::error::app process not alive after launch"
  adb logcat -d -t 400 | grep -E "FATAL|AndroidRuntime|$APP_PACKAGE" || true
  exit 1
fi

# Never upload a stale or empty screenshot as successful evidence.
tmp_screen=$(mktemp "${SCREEN}.XXXXXX")
trap 'rm -f "$tmp_screen"' EXIT
adb exec-out screencap -p > "$tmp_screen"
if [ "$(od -An -tx1 -N8 "$tmp_screen" | tr -d ' \n')" != 89504e470d0a1a0a ] || [ "$(wc -c < "$tmp_screen")" -le 8 ]; then
  echo "::error::screenshot is not a nonempty PNG"
  exit 1
fi
mv "$tmp_screen" "$SCREEN"
printf 'screenshot_sha256=%s\n' "$(sha256sum "$SCREEN" | cut -d ' ' -f 1)"
printf 'ended_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "emulator startup smoke passed; screenshot $(wc -c < "$SCREEN") bytes"
