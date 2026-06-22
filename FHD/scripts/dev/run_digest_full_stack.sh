#!/usr/bin/env bash
# 一键：MODstore 日更栈 → 自动拉起截图依赖（FHD/Vite/模拟器）→ 立即 digest → 可选收尾
#
# 用法：
#   bash FHD/scripts/dev/run_digest_full_stack.sh
#   MODSTORE_SURFACE_AUDIT_STOP_AFTER=1 bash FHD/scripts/dev/run_digest_full_stack.sh  # 跑完关临时进程
#
# 说明：
# - P-W 默认打 https://xiu-ci.com（公网），不需本地营销静态服
# - P-S 自动起 :5000 API + :5001 Vite（MODSTORE_SURFACE_AUDIT_AUTO_START=1）
# - P-App 自动起模拟器 adb 全量（需本机 Android SDK）
# - MODstore :8788 若已在跑且 scheduler 已开，默认不重启；改 env 后设 MODSTORE_DAILY_FORCE_RESTART=1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log() { printf '[digest-full-stack] %s\n' "$*"; }

export MODSTORE_SURFACE_AUDIT_AUTO_START="${MODSTORE_SURFACE_AUDIT_AUTO_START:-1}"
export MODSTORE_SURFACE_AUDIT_ANDROID="${MODSTORE_SURFACE_AUDIT_ANDROID:-1}"
export MODSTORE_SURFACE_AUDIT_PS_ENABLED="${MODSTORE_SURFACE_AUDIT_PS_ENABLED:-1}"
export MODSTORE_DAILY_SURFACE_AUDIT_MODE="${MODSTORE_DAILY_SURFACE_AUDIT_MODE:-daily}"
export MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC="${MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC:-1800}"
export MODSTORE_DIGEST_HTTP_TIMEOUT_SEC="${MODSTORE_DIGEST_HTTP_TIMEOUT_SEC:-${MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC}}"
export MODSTORE_SURFACE_AUDIT_SKIP_CATALOG="${MODSTORE_SURFACE_AUDIT_SKIP_CATALOG:-0}"
export MODSTORE_SURFACE_AUDIT_CATALOG_MAX="${MODSTORE_SURFACE_AUDIT_CATALOG_MAX:-3}"
export SURFACE_AUDIT_API_URL="${SURFACE_AUDIT_API_URL:-http://127.0.0.1:5102}"
export SURFACE_AUDIT_ANDROID_FHD_HOST="${SURFACE_AUDIT_ANDROID_FHD_HOST:-10.0.2.2:5000}"

export MODSTORE_SURFACE_AUDIT_STOP_AFTER="${MODSTORE_SURFACE_AUDIT_STOP_AFTER:-1}"

log "1/3 确保 MODstore 日更栈 (:8788 + scheduler) …"
MODSTORE_DAILY_FORCE_RESTART="${MODSTORE_DAILY_FORCE_RESTART:-0}" \
  bash "${SCRIPT_DIR}/run_modstore_daily_local.sh"

log "2/3 触发 digest（内含 ensure_surface_audit_deps 自动拉起 FHD/Vite/模拟器）…"
log "     超时最长 ${MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC:-1800}s，日志见 .xcmax-logs/surface-audit-*.log"
bash "${SCRIPT_DIR}/trigger_digest_now_local.sh"

if [[ "${MODSTORE_SURFACE_AUDIT_STOP_AFTER:-1}" == "1" ]]; then
  log "3/3 digest 内已配置 STOP_AFTER=1，临时进程由 Python finally 自动关闭"
  bash "${SCRIPT_DIR}/stop_surface_audit_stack.sh" 2>/dev/null || true
else
  log "3/3 完成。临时进程仍在后台；收尾：bash FHD/scripts/dev/stop_surface_audit_stack.sh"
fi
