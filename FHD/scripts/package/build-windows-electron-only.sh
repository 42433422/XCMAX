#!/usr/bin/env bash
# macOS/Linux：仅交叉编译 Windows Electron 壳（不含 PyInstaller 后端）。
# 仅用于诊断的薄壳；完整内嵌后端请使用正式构建链。
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/../deploy/lib/version.sh"
VERSION="${1:-$(product_version)}"
SKU="${2:-enterprise}"
VERSION="${VERSION#[vV]}"
TOOLCHAIN_VERSION="$(printf '%s' "${VERSION}" | cut -d. -f1-3)"

if [[ "${SKU}" != enterprise ]]; then
  echo "[err] Windows payload supports only the enterprise SKU" >&2
  exit 1
fi

if [[ "${XCAGI_ALLOW_WINDOWS_THIN_SHELL:-0}" != "1" ]]; then
  cat >&2 <<'EOF'
[err] Windows Electron-only thin shell is disabled for release builds.
      It produces an installer without resources/backend/xcagi-backend.exe,
      so the installed Windows app cannot start the embedded backend.
      Use scripts/package/build-installer.ps1 on Windows for the WPF installer.
      For a diagnostic shell-only build, set XCAGI_ALLOW_WINDOWS_THIN_SHELL=1.
EOF
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then PYTHON="${ROOT}/.venv/bin/python"; fi

LABEL=Enterprise
OUT_DIR="${ROOT}/release/_windows-payload/${VERSION}/${SKU}-thin"
mkdir -p "${OUT_DIR}"

echo "========== Windows Electron-only SKU: ${SKU} =========="

bash scripts/package/stage-bundled-mods.sh "${SKU}" || true

(cd frontend && [ -d node_modules ] || npm install)
(cd frontend && VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full npm run build:full)
# 桌面包不构建 admin-console（管理端仅网页 SSOT）

printf '{"sku":"%s","schema_version":1}\n' "${SKU}" > desktop/resources/product-sku.json
"${PYTHON}" scripts/package/generate-desktop-resources.py

# 薄壳模式：不打包 Mac/Linux PyInstaller 产物（Windows 无法运行）
rm -rf "${ROOT}/dist/xcagi-backend"

(cd desktop && [ -d node_modules ] || npm install)
npm version "${TOOLCHAIN_VERSION}" --no-git-tag-version --prefix desktop --allow-same-version

ARTIFACT="XCAGI-${LABEL}-Setup-${VERSION}-\${arch}.\${ext}"

(
  cd desktop
  npx electron-builder --win nsis zip --x64 --publish never \
    "--config.directories.output=${OUT_DIR}" \
    "--config.appId=com.xcagi.desktop.enterprise" \
    "--config.publish.url=https://xiu-ci.com/releases/stable/enterprise/" \
    "--config.nsis.artifactName=${ARTIFACT}" \
    "--config.buildVersion=${VERSION}" \
    "--config.extraMetadata.shortVersionWindows=${VERSION}" \
    "--config.extraMetadata.productSku=${SKU}"
)

SETUP="$(find "${OUT_DIR}" -maxdepth 1 -type f -name "XCAGI-${LABEL}-Setup-*.exe" | sort | tail -1)"
[[ -n "${SETUP}" ]] || SETUP="$(find "${OUT_DIR}" -maxdepth 1 -type f -name "XCAGI-*-Setup-*.exe" | sort | tail -1)"
[[ -n "${SETUP}" ]] || { echo "[err] 未找到 exe" >&2; exit 1; }

FINAL="${OUT_DIR}/XCAGI-${LABEL}-Setup-${VERSION}-x64.exe"
[[ "${SETUP}" == "${FINAL}" ]] || mv -f "${SETUP}" "${FINAL}"

XCAGI_PRODUCT_VERSION="${VERSION}" \
  node scripts/package/generate-update-metadata.mjs "${FINAL}" "${TOOLCHAIN_VERSION}" win
echo "[ok] ${FINAL} (electron-only; 内嵌后端需 Windows 构建链)"
