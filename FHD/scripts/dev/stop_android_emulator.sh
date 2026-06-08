#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SDK="${FHD_ROOT}/mobile-android/.toolchain/android-sdk"
ADB="${SDK}/platform-tools/adb"
PID_FILE="${FHD_ROOT}/data/surface_audit/.android-emulator.pid"

if [[ -f "${PID_FILE}" ]]; then
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" 2>/dev/null || true
  rm -f "${PID_FILE}"
fi

if [[ -x "${ADB}" ]]; then
  "${ADB}" emu kill 2>/dev/null || true
fi
printf '[android-emulator] 已停止\n'
