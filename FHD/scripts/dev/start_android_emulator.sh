#!/usr/bin/env bash
# 启动 P-App 巡检用 Android 模拟器（默认无窗口 headless，可 GUI）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="${MODSTORE_DAILY_FHD_ROOT:-${XCAGI_FHD_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
SDK="${XCAGI_ANDROID_SDK_ROOT:-${ANDROID_SDK_ROOT:-${FHD_ROOT}/mobile-android/.toolchain/android-sdk}}"
AVD_NAME="${XCAGI_ANDROID_AVD:-xcagi_surface_audit}"
ADB="${SDK}/platform-tools/adb"
EMULATOR="${SDK}/emulator/emulator"
PID_FILE="${XCAGI_ANDROID_EMULATOR_PID_FILE:-${FHD_ROOT}/data/surface_audit/.android-emulator.pid}"
LOG_FILE="${XCAGI_ANDROID_EMULATOR_LOG_FILE:-${FHD_ROOT}/data/surface_audit/android-emulator.log}"
HEADLESS="${XCAGI_ANDROID_EMULATOR_HEADLESS:-1}"
BOOT_TIMEOUT="${XCAGI_ANDROID_BOOT_TIMEOUT:-180}"
STABLE_SECONDS="${XCAGI_ANDROID_STABLE_SECONDS:-10}"
GPU_MODE="${XCAGI_ANDROID_EMULATOR_GPU:-}"

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
  for _ in $(seq 1 "${STABLE_SECONDS}"); do
    if ! "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
      log "ERROR: adb device 在线后又消失"
      exit 1
    fi
    sleep 1
  done
  exit 0
fi

if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    log "检测到旧模拟器进程 pid=${OLD_PID}，等待 adb device …"
    for _ in $(seq 1 "${BOOT_TIMEOUT}"); do
      if "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
        log "旧模拟器进程已就绪"
        exit 0
      fi
      if ! kill -0 "${OLD_PID}" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    log "旧模拟器进程不可用，清理 pid=${OLD_PID}"
    kill "${OLD_PID}" 2>/dev/null || true
    sleep 2
  fi
  rm -f "${PID_FILE}"
fi

EMU_ARGS=(-avd "${AVD_NAME}" -no-boot-anim -no-snapshot-save)
if [[ "${HEADLESS}" == "1" ]]; then
  EMU_ARGS+=(-no-window -no-audio)
fi
if [[ -z "${GPU_MODE}" ]]; then
  if [[ "${HEADLESS}" == "1" ]]; then
    GPU_MODE="swiftshader_indirect"
  elif [[ "$(uname -m)" == "arm64" ]]; then
    GPU_MODE="host"
  else
    GPU_MODE="swiftshader_indirect"
  fi
fi
EMU_ARGS+=(-gpu "${GPU_MODE}")

log "启动 ${AVD_NAME} (headless=${HEADLESS}, gpu=${GPU_MODE}) …"
nohup "${EMULATOR}" "${EMU_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
echo $! >"${PID_FILE}"
EMU_PID="$!"

log "等待 adb device（最长 ${BOOT_TIMEOUT}s）…"
for _ in $(seq 1 "${BOOT_TIMEOUT}"); do
  if ! kill -0 "${EMU_PID}" 2>/dev/null; then
    log "ERROR: emulator 进程提前退出，查看日志: ${LOG_FILE}"
    rm -f "${PID_FILE}"
    exit 1
  fi
  if "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
    "${ADB}" wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 1; done' 2>/dev/null || true
    for _ in $(seq 1 "${STABLE_SECONDS}"); do
      if ! kill -0 "${EMU_PID}" 2>/dev/null; then
        log "ERROR: emulator boot 后退出，查看日志: ${LOG_FILE}"
        rm -f "${PID_FILE}"
        exit 1
      fi
      if ! "${ADB}" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device'; then
        log "ERROR: adb device boot 后消失，查看日志: ${LOG_FILE}"
        exit 1
      fi
      sleep 1
    done
    log "模拟器就绪且稳定"
    "${ADB}" devices
    exit 0
  fi
  sleep 1
done

log "ERROR: 启动超时，查看日志: ${LOG_FILE}"
rm -f "${PID_FILE}"
exit 1
