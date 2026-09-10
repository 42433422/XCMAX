#!/usr/bin/env bash
# Android 真机冒烟：安装 debug APK → 冷启动 → 断言进程存活 → 截图留证。
# 由 .github/workflows/ci-mobile-android-smoke.yml 在 emulator-runner 的
# script: 内调用（该 action 会逐行拆分 script 为独立进程，故逻辑必须落盘）。
# 调用时 cwd = FHD/mobile-flutter-poc。
set -euo pipefail

APP_PACKAGE="${APP_PACKAGE:?APP_PACKAGE must be set}"

APK=$(find build/app/outputs/flutter-apk -name 'app-debug.apk' | head -1)
if [ -z "$APK" ]; then
  echo "::error::debug APK not found after build"
  exit 1
fi
echo "installing $APK"
adb install -r -g "$APK"

# 冷启动主 Activity，等待首帧渲染
adb shell monkey -p "$APP_PACKAGE" -c android.intent.category.LAUNCHER 1
sleep 15

# 存活断言：进程仍在 = 启动路径（含 MethodChannel/插件初始化）未崩溃
if [ -z "$(adb shell pidof "$APP_PACKAGE" || true)" ]; then
  echo "::error::app process not alive after launch"
  adb logcat -d -t 400 | grep -E "FATAL|AndroidRuntime|$APP_PACKAGE" || true
  exit 1
fi

adb exec-out screencap -p > /tmp/android-smoke-screen.png
echo "smoke passed; screenshot $(wc -c < /tmp/android-smoke-screen.png) bytes"
