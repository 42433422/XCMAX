#!/usr/bin/env bash
# macOS/Linux：仅交叉编译 Windows Electron 壳（不含 PyInstaller 后端）。
# 与 update 站上 Personal 10.0.0 薄壳安装包同构；完整内嵌后端请用 Windows 跑 build-installer.ps1。
set -euo pipefail

VERSION="${1:-10.0.0}"
SKU="${2:-enterprise}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"

case "${SKU}" in
  personal | enterprise) ;;
  *) echo "[err] SKU 须为 personal 或 enterprise" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then PYTHON="${ROOT}/.venv/bin/python"; fi

sku_label() { case "$1" in personal) echo Personal ;; enterprise) echo Enterprise ;; esac; }
sku_app_id() { case "$1" in personal) echo com.xcagi.desktop.personal ;; enterprise) echo com.xcagi.desktop.enterprise ;; esac; }
sku_update_url() {
  case "$1" in
    personal) echo https://update.xcagi.com/releases/stable/personal/ ;;
    enterprise) echo https://update.xcagi.com/releases/stable/enterprise/ ;;
  esac
}

LABEL="$(sku_label "${SKU}")"
OUT_DIR="${ROOT}/release/xcagi-v${VERSION}/${SKU}"
mkdir -p "${OUT_DIR}"

echo "========== Windows Electron-only SKU: ${SKU} =========="

bash scripts/package/stage-bundled-mods.sh "${SKU}" || true

(cd frontend && [ -d node_modules ] || npm install)
if [[ "${SKU}" == "personal" ]]; then
  (cd frontend && npm run build:minimal)
else
  (cd frontend && VITE_XCAGI_PRODUCT_SKU=enterprise npm run build)
fi

printf '{"sku":"%s","schema_version":1}\n' "${SKU}" > desktop/resources/product-sku.json
"${PYTHON}" scripts/package/generate-desktop-resources.py

# 薄壳模式：不打包 Mac/Linux PyInstaller 产物（Windows 无法运行）
rm -rf "${ROOT}/dist/xcagi-backend"

(cd desktop && [ -d node_modules ] || npm install)
npm version "${VERSION}" --no-git-tag-version --prefix desktop --allow-same-version

APP_ID="$(sku_app_id "${SKU}")"
PUBLISH_URL="$(sku_update_url "${SKU}")"
ARTIFACT="XCAGI-${LABEL}-Setup-\${version}-\${arch}.\${ext}"

(
  cd desktop
  npx electron-builder --win nsis zip --x64 \
    "--config.directories.output=../release/xcagi-v${VERSION}/${SKU}" \
    "--config.appId=${APP_ID}" \
    "--config.publish.url=${PUBLISH_URL}" \
    "--config.nsis.artifactName=${ARTIFACT}" \
    "--config.extraMetadata.productSku=${SKU}"
)

SETUP="$(find "${OUT_DIR}" -maxdepth 1 -type f -name "XCAGI-${LABEL}-Setup-*.exe" | sort | tail -1)"
[[ -n "${SETUP}" ]] || SETUP="$(find "${OUT_DIR}" -maxdepth 1 -type f -name "XCAGI-*-Setup-*.exe" | sort | tail -1)"
[[ -n "${SETUP}" ]] || { echo "[err] 未找到 exe" >&2; exit 1; }

FINAL="${OUT_DIR}/XCAGI-${LABEL}-Setup-${VERSION}-x64.exe"
[[ "${SETUP}" == "${FINAL}" ]] || mv -f "${SETUP}" "${FINAL}"

node scripts/package/generate-update-metadata.mjs "${FINAL}" "${VERSION}" win
echo "[ok] ${FINAL} (electron-only; 内嵌后端需 Windows 构建链)"
