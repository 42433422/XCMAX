#!/usr/bin/env bash
# P-App 移动/WebView 全页面截图巡检（SA 节点）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND="${FHD_ROOT}/frontend"
LANE="${SURFACE_AUDIT_LANE:-P-App}"
API_PORT="${E2E_API_PORT:-5000}"
WEB_PORT="${E2E_WEB_PORT:-5001}"

log() { printf '[surface-audit] %s\n' "$*"; }

export SURFACE_AUDIT_BASE_URL="${SURFACE_AUDIT_BASE_URL:-http://127.0.0.1:${WEB_PORT}}"
export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:5176}"
export SURFACE_AUDIT_PRODUCT_SKU="${SURFACE_AUDIT_PRODUCT_SKU:-personal}"
# 有 adb 设备时自动合并原生屏真机截图（可显式 SURFACE_AUDIT_ANDROID=0 关闭）
ADB_BIN="${FHD_ROOT}/mobile-android/.toolchain/android-sdk/platform-tools/adb"
[[ -x "${ADB_BIN}" ]] || ADB_BIN="adb"
if [[ "${SURFACE_AUDIT_ANDROID:-}" == "" ]]; then
  if ! "${ADB_BIN}" devices 2>/dev/null | grep -qE 'device$'; then
    if [[ "${XCAGI_AUTO_START_EMULATOR:-1}" == "1" && -x "${FHD_ROOT}/mobile-android/.toolchain/android-sdk/emulator/emulator" ]]; then
      log "无在线设备，尝试启动本地模拟器 …"
      bash "${SCRIPT_DIR}/start_android_emulator.sh" || log "模拟器启动失败，将仅用 Web 占位"
    fi
  fi
  if "${ADB_BIN}" devices 2>/dev/null | grep -qE 'device$'; then
    export SURFACE_AUDIT_ANDROID=1
    export SURFACE_AUDIT_ANDROID_ADB="${ADB_BIN}"
    log "检测到 Android 设备，启用 adb 原生屏截图"
  fi
fi
export SURFACE_AUDIT_ANDROID_FHD_HOST="${SURFACE_AUDIT_ANDROID_FHD_HOST:-10.0.2.2:${API_PORT}}"
export SURFACE_AUDIT_API_URL="${SURFACE_AUDIT_API_URL:-http://127.0.0.1:${API_PORT}}"
export SURFACE_AUDIT_USER="${SURFACE_AUDIT_USER:-admin}"
export SURFACE_AUDIT_PASSWORD="${SURFACE_AUDIT_PASSWORD:-admin123}"
export SURFACE_AUDIT_ACCOUNT_KIND="${SURFACE_AUDIT_ACCOUNT_KIND:-admin}"

wait_http() {
  local url="$1" label="$2" n="${3:-45}"
  for _ in $(seq 1 "$n"); do
    if curl -sf "$url" >/dev/null 2>&1; then
      log "${label} 就绪: ${url}"
      return 0
    fi
    sleep 1
  done
  log "警告: ${label} 未就绪 (${url})，巡检可能部分失败"
  return 1
}

if ! curl -sf "http://127.0.0.1:${WEB_PORT}/" >/dev/null 2>&1; then
  log "启动 Vite :${WEB_PORT} …"
  (
    cd "${FRONTEND}"
    export VITE_XCAGI_PRODUCT_SKU="${SURFACE_AUDIT_PRODUCT_SKU}"
    exec npm run dev -- --host 127.0.0.1 --port "${WEB_PORT}"
  ) &
  VITE_PID=$!
  trap 'kill ${VITE_PID} 2>/dev/null || true' EXIT
  wait_http "http://127.0.0.1:${WEB_PORT}/" "Vite" || true
fi

cd "${FRONTEND}"
if [[ -d node_modules/@playwright/test ]]; then
  npx playwright install chromium 2>/dev/null || true
else
  log "ERROR: 请先 cd FHD/frontend && npm ci"
  exit 1
fi

OUT="${FHD_ROOT}/data/surface_audit/${LANE}/$(date +%Y-%m-%d).json"
mkdir -p "$(dirname "${OUT}")"
log "巡检 lane=${LANE} → ${OUT}"
node "${FHD_ROOT}/scripts/ci/run_surface_audit.mjs" "${LANE}" --refresh --out "${OUT}"
log "完成: $(python3 -c "import json; d=json.load(open('${OUT}')); print(d.get('page_count',0), 'pages')")"
