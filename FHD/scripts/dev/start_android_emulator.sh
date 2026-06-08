#!/usr/bin/env bash
# 启动 P-App 巡检用 Android 模拟器（默认无窗口 headless，可 GUI）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SDK="${FHD_ROOT}/mobile-android/.toolchain/android-sdk"
AVD_NAME="${XCAGI_ANDROID_AVD:-xcagi_surface_audit}"
ADB="${SDK}/platform-tools/adb"
EMULATOR="${SDK}/emulator/emulator"
PID_FILE="${FHD_ROOT}/data/surface_audit/.android-emulator.pid"
LOG_FILE="${FHD_ROOT}/data/surface_audit/android-emulator.log"
HEADLESS="${XCAGI_ANDROID_EMULATOR_HEADLESS:-1}"
BOOT_TIMEOUT="${XCAGI_ANDROID_BOOT_TIMEOUT:-180}"

log() { printf '[android-emulator] %s\n' "$*"; }

if [[ -z "${JAVA_HOME:-}" && -d "${FHD_ROOT}/.tools/jdk-17/Contents/Home" ]]; then
  export JAVA_HOME="${FHD_ROOT}/.tools/jdk-17/Contents/Home"
fi
export ANDROID_HOME="${ANDROID_HOME:-${SDK}}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
export PATH="${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"

mkdir -p "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"

if [[ ! -x "${EMULATOR}" ]]; then
  log "ERROR: 未安装 emulator，请先运行: bash FHD/scripts/dev/setup_android_emulator.sh"
  exit 1
fi

# 已有在线设备则直接退出
if "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
  log "模拟器已在线: $("${ADB}" devices | awk '/emulator-.*device/{print $1}')"
  exit 0
fi

EMU_ARGS=(-avd "${AVD_NAME}" -no-boot-anim -no-snapshot-save)
if [[ "${HEADLESS}" == "1" ]]; then
  EMU_ARGS+=(-no-window -no-audio)
fi
# Apple Silicon / 现代 Mac 优先 host GPU
if [[ "$(uname -m)" == "arm64" ]]; then
  EMU_ARGS+=(-gpu host)
else
  EMU_ARGS+=(-gpu swiftshader_indirect)
fi

log "启动 ${AVD_NAME} (headless=${HEADLESS}) …"
nohup "${EMULATOR}" "${EMU_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
echo $! >"${PID_FILE}"

log "等待 adb device（最长 ${BOOT_TIMEOUT}s）…"
for _ in $(seq 1 "${BOOT_TIMEOUT}"); do
  if "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
    "${ADB}" wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 1; done' 2>/dev/null || true
    log "模拟器就绪"
    "${ADB}" devices
    exit 0
  fi
  sleep 1
done

log "ERROR: 启动超时，查看日志: ${LOG_FILE}"
exit 1
