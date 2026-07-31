#!/usr/bin/env bash
# 将最新 frontend 构建产物同步到本机已安装的 XCAGI（桌面包不含 admin-vue-dist）。
# macOS：优先写 /Applications；无写权限时输出到 Desktop/XCAGI-fixed.app 并 ad-hoc 签名。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${ROOT}/templates/vue-dist"
BUILD=0
EDITION="${EDITION:-generic}"
PRODUCT_SKU="${PRODUCT_SKU:-enterprise}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1; shift ;;
    --edition) EDITION="$2"; shift 2 ;;
    --sku) PRODUCT_SKU="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

case "${PRODUCT_SKU}" in
  personal) EDITION=minimal ;;
  enterprise) EDITION=full ;;
esac

if [[ "${BUILD}" -eq 1 || ! -f "${SRC}/index.html" ]]; then
  (
    cd "${ROOT}/frontend"
    [[ -d node_modules ]] || npm install
    export VITE_XCAGI_PRODUCT_SKU="${PRODUCT_SKU}"
    export VITE_XCAGI_EDITION="${EDITION}"
    case "${EDITION}" in
      minimal) npm run build:minimal ;;
      full) npm run build:full ;;
      *) npm run build ;;
    esac
  )
fi

if [[ ! -f "${SRC}/index.html" ]]; then
  echo "[err] missing ${SRC}/index.html — pass --build or build frontend first" >&2
  exit 1
fi

JS_COUNT="$(find "${SRC}/assets/js" -type f -name '*.js' 2>/dev/null | wc -l | tr -d ' ')"
HASH="$(python3 -c "
from pathlib import Path
import re
html = Path(r'''${SRC}/index.html''').read_text(encoding='utf-8', errors='ignore')
m = re.search(r'index-([A-Za-z0-9_-]+)\\.js', html)
print(m.group(1) if m else 'unknown')
")"

sync_one() {
  local dst="$1"
  local parent
  parent="$(dirname "${dst}")"
  [[ -d "${parent}" ]] || return 1
  mkdir -p "${parent}"
  rsync -a --delete "${SRC}/" "${dst}/"
  [[ -f "${dst}/index.html" ]]
}

synced=0
if sync_one "/Applications/XCAGI.app/Contents/Resources/backend/_internal/templates/vue-dist" 2>/dev/null; then
  synced=$((synced + 1))
  echo "[ok] synced /Applications/XCAGI.app (may need re-sign / replace from Desktop if Gatekeeper blocks)"
else
  echo "[warn] cannot write /Applications/XCAGI.app — building Desktop/XCAGI-fixed.app"
  APP_SRC="/Applications/XCAGI.app"
  APP_DST="${HOME}/Desktop/XCAGI-fixed.app"
  if [[ ! -d "${APP_SRC}" ]]; then
    echo "[err] ${APP_SRC} not found" >&2
    exit 1
  fi
  rm -rf "${APP_DST}"
  ditto "${APP_SRC}" "${APP_DST}"
  sync_one "${APP_DST}/Contents/Resources/backend/_internal/templates/vue-dist"
  codesign --force --deep --sign - "${APP_DST}" >/dev/null
  xattr -cr "${APP_DST}" 2>/dev/null || true
  synced=$((synced + 1))
  echo "[ok] wrote ${APP_DST} (ad-hoc signed). Open that app, not /Applications/XCAGI.app"
fi

UD="${HOME}/Library/Application Support/XCAGI"
for sub in Cache "Code Cache" GPUCache DawnGraphiteCache DawnWebGPUCache blob_storage; do
  rm -rf "${UD}/${sub}" 2>/dev/null || true
done
rm -f "${UD}/frontend-cache-version.txt" 2>/dev/null || true

echo "Synced vue-dist (edition=${EDITION}, index-${HASH}.js, js=${JS_COUNT}) -> ${synced} path(s)."
echo "Desktop package does not include admin-vue-dist (web admin only)."
echo "Restart XCAGI after sync."
