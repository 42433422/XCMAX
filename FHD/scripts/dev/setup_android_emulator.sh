#!/usr/bin/env bash
# 安装 Android 模拟器组件并创建 P-App 巡检用 AVD（Pixel 7 · API 35 · arm64）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ANDROID_DIR="${FHD_ROOT}/mobile-android"
SDK="${ANDROID_DIR}/.toolchain/android-sdk"
AVD_NAME="${XCAGI_ANDROID_AVD:-xcagi_surface_audit}"
SYS_IMG="${XCAGI_ANDROID_SYS_IMAGE:-system-images;android-35;google_apis;arm64-v8a}"
DEVICE_PROFILE="${XCAGI_ANDROID_DEVICE:-pixel_7}"

log() { printf '[android-emulator-setup] %s\n' "$*"; }

if [[ -z "${JAVA_HOME:-}" && -d "${FHD_ROOT}/.tools/jdk-17/Contents/Home" ]]; then
  export JAVA_HOME="${FHD_ROOT}/.tools/jdk-17/Contents/Home"
fi
export ANDROID_HOME="${ANDROID_HOME:-${SDK}}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
export PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"

SDKM="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"
AVDM="${ANDROID_HOME}/cmdline-tools/latest/bin/avdmanager"

if [[ ! -x "${SDKM}" ]]; then
  log "ERROR: sdkmanager 不存在，请先配置 mobile-android/.toolchain/android-sdk"
  exit 1
fi

log "接受 SDK 许可 …"
yes | "${SDKM}" --licenses >/dev/null 2>&1 || true

log "安装 emulator + 系统镜像 (${SYS_IMG}) …"
"${SDKM}" --install "emulator" "${SYS_IMG}"

if "${AVDM}" list avd 2>/dev/null | grep -q "Name: ${AVD_NAME}"; then
  log "AVD 已存在: ${AVD_NAME}"
else
  log "创建 AVD: ${AVD_NAME} (${DEVICE_PROFILE})"
  echo no | "${AVDM}" create avd \
    -n "${AVD_NAME}" \
    -k "${SYS_IMG}" \
    -d "${DEVICE_PROFILE}" \
    --force
fi

log "完成。启动: bash FHD/scripts/dev/start_android_emulator.sh"
"${AVDM}" list avd | sed -n '1,12p'
