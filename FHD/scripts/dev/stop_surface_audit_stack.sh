#!/usr/bin/env bash
# 停止 digest 截图时由 surface_audit_deps 拉起的临时进程（FHD :5000 / Vite :5001 / 静态服等）
# 用法：bash FHD/scripts/dev/stop_surface_audit_stack.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
PIDS_DIR="${XCMAX_ROOT}/.xcmax-pids"
EMU_PID="${FHD_ROOT}/data/surface_audit/.android-emulator.pid"

log() { printf '[stop-surface-audit] %s\n' "$*"; }

stop_pid_file() {
  local label="$1"
  local file="$2"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(tr -d '[:space:]' < "$file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    log "停止 ${label} pid=${pid}"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$file"
}

if [[ -d "${PIDS_DIR}" ]]; then
  for pf in "${PIDS_DIR}"/surface-audit-*.pid; do
    [[ -f "$pf" ]] || continue
    stop_pid_file "$(basename "$pf" .pid)" "$pf"
  done
fi

stop_pid_file "android-emulator" "$EMU_PID"
log "完成（MODstore :8788 日更栈未动；需停请 lsof -ti :8788 | xargs kill）"
