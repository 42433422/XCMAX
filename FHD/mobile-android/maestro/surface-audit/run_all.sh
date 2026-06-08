#!/usr/bin/env bash
# Maestro 批量原生屏截图（需已安装 maestro CLI + 设备在线）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CONFIG="${FHD_ROOT}/config/surface_audit_pages.json"
OUT_DIR="${FHD_ROOT}/data/surface_audit/android-maestro/$(date +%Y-%m-%d)"
APP_ID="${SURFACE_AUDIT_ANDROID_PACKAGE:-com.xiuci.xcagi.mobile.personal}"
FHD_HOST="${SURFACE_AUDIT_ANDROID_FHD_HOST:-10.0.2.2:5000}"
MOD_ID="${SURFACE_AUDIT_SAMPLE_MOD_ID:-taiyangniao-pro}"

if ! command -v maestro >/dev/null 2>&1; then
  echo "[maestro] 未安装 maestro CLI，请改用: SURFACE_AUDIT_ANDROID=1 make surface-audit-app"
  exit 1
fi

mkdir -p "${OUT_DIR}"
FLOW="${SCRIPT_DIR}/capture_page.yaml"

while IFS=$'\t' read -r pid route; do
  echo "[maestro] ${pid} → ${route}"
  maestro test "${FLOW}" \
    -e "APP_ID=${APP_ID}" \
    -e "PAGE_ROUTE=${route}" \
    -e "FHD_HOST=${FHD_HOST}" || true
done < <(python3 -c "
import json, pathlib, os
cfg = json.loads(pathlib.Path('${CONFIG}').read_text())
mod = os.environ.get('SURFACE_AUDIT_SAMPLE_MOD_ID', '${MOD_ID}')
for p in cfg['lanes']['P-App']['pages']:
    if not p.get('native'):
        continue
    r = p.get('android_route') or p['id']
    if p['id'] == 'mod_web':
        r = f'mod/{mod}'
    print(p['id'], r, sep='\t')
")

echo "[maestro] 完成；Maestro 默认截图在 ~/.maestro/tests"
