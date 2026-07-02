#!/usr/bin/env bash
# macOS/Linux：Docker+Wine 交叉编译 Windows NSIS 安装包（personal | enterprise）。
# 等价于 build-installer.ps1 -SkipUiInstaller（跳过 WPF 外壳，保留 NSIS + 内嵌后端）。
set -euo pipefail

VERSION="${1:-10.0.0}"
SKU="${2:-enterprise}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"

case "${SKU}" in
  personal | enterprise) ;;
  *)
    echo "[err] SKU 须为 personal 或 enterprise，当前: ${SKU}" >&2
    exit 1
    ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi
export PYTHON

sku_label() {
  case "$1" in
    personal) echo Personal ;;
    enterprise) echo Enterprise ;;
  esac
}

sku_app_id() {
  case "$1" in
    personal) echo com.xcagi.desktop.personal ;;
    enterprise) echo com.xcagi.desktop.enterprise ;;
  esac
}

sku_update_url() {
  case "$1" in
    personal) echo https://update.xcagi.com/releases/stable/personal/ ;;
    enterprise) echo https://update.xcagi.com/releases/stable/enterprise/ ;;
  esac
}

LABEL="$(sku_label "${SKU}")"
OUT_DIR="${ROOT}/release/xcagi-v${VERSION}/${SKU}"
mkdir -p "${OUT_DIR}"

echo "========== Windows SKU (docker/wine): ${SKU} =========="

bash scripts/package/stage-bundled-mods.sh "${SKU}"
bash scripts/package/stage-industry-seeds.sh "${SKU}"
mkdir -p build
printf '{"sku":"%s","schema_version":1}\n' "${SKU}" > build/product-sku.json
export XCAGI_PRODUCT_SKU="${SKU}"
export XCAGI_STAGED_MODS_DIR="${ROOT}/build/staged-mods-${SKU}"
export XCAGI_MODS_ROOT="${XCAGI_STAGED_MODS_DIR}"
export XCAGI_STAGED_INDUSTRY_SEEDS_DIR="${ROOT}/build/staged-industry-seeds-${SKU}"

# 前端
(cd frontend && [ -d node_modules ] || npm install)
if [[ "${SKU}" == "personal" ]]; then
  (cd frontend && VITE_XCAGI_PRODUCT_SKU=personal VITE_XCAGI_EDITION=minimal npm run build:minimal)
else
  (cd frontend && VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full npm run build:full)
fi

"${PYTHON}" scripts/package/generate_mods_index.py

# PyInstaller（Wine · Windows 目标）
WINE_IMAGE="${XCAGI_WINE_BUILD_IMAGE:-docker.m.daocloud.io/electronuserland/builder:wine}"
if ! docker image inspect "${WINE_IMAGE}" >/dev/null 2>&1; then
  echo "[info] pulling ${WINE_IMAGE} ..."
  docker pull "${WINE_IMAGE}"
fi

docker run --rm --platform linux/amd64 \
  -v "${ROOT}:/project" \
  -w /project \
  -e XCAGI_VERSION="${VERSION}" \
  -e XCAGI_PRODUCT_SKU="${SKU}" \
  -e XCAGI_STAGED_MODS_DIR="/project/build/staged-mods-${SKU}" \
  -e XCAGI_MODS_ROOT="/project/build/staged-mods-${SKU}" \
  -e XCAGI_STAGED_INDUSTRY_SEEDS_DIR="/project/build/staged-industry-seeds-${SKU}" \
  "${WINE_IMAGE}" \
  /bin/bash -lc '
    set -euo pipefail
    wine64 cmd /c "python -m pip install --upgrade pip" || true
    wine64 python -m pip install --upgrade pip
    grep -Ev "^[[:space:]]*(#|-e|pytest($|[-=<>]))" XCAGI/requirements.txt | grep -Ev "^[[:space:]]*$" > /tmp/runtime-req.txt || true
    if [ -s /tmp/runtime-req.txt ]; then wine64 python -m pip install -r /tmp/runtime-req.txt; fi
    wine64 python -m pip install "pyinstaller>=6.0" appdirs
    wine64 python -m PyInstaller --noconfirm --clean scripts/package/xcagi_backend.spec
  '

BACKEND_EXE="${ROOT}/dist/xcagi-backend/xcagi-backend.exe"
if [[ ! -f "${BACKEND_EXE}" ]]; then
  echo "[err] Windows backend executable missing: ${BACKEND_EXE}" >&2
  exit 1
fi

printf '%s\n' "${VERSION}" > release/VERSION
printf '{"sku":"%s","schema_version":1}\n' "${SKU}" > desktop/resources/product-sku.json

"${PYTHON}" scripts/package/generate-desktop-resources.py

# Electron NSIS（宿主 electron-builder 可交叉编译 win）
(cd desktop && [ -d node_modules ] || npm install)
(cd desktop && npm run build)
for marker in "packagedBackendCandidates" "electron-backend.log" "backend', '_internal'" "180_000"; do
  if ! grep -Fq "${marker}" desktop/dist/main.js; then
    echo "[err] Electron main bundle is stale; missing marker: ${marker}" >&2
    exit 1
  fi
done
npm version "${VERSION}" --no-git-tag-version --prefix desktop
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
if [[ -z "${SETUP}" ]]; then
  SETUP="$(find "${OUT_DIR}" -maxdepth 1 -type f -name "XCAGI-*-Setup-*.exe" | sort | tail -1)"
fi
if [[ -z "${SETUP}" ]]; then
  echo "[err] 未找到 NSIS exe，目录: ${OUT_DIR}" >&2
  ls -la "${OUT_DIR}" >&2 || true
  exit 1
fi

FINAL="${OUT_DIR}/XCAGI-${LABEL}-Setup-${VERSION}-x64.exe"
if [[ "${SETUP}" != "${FINAL}" ]]; then
  mv -f "${SETUP}" "${FINAL}"
fi

UNPACKED="${OUT_DIR}/win-unpacked/resources"
for required in \
  "${UNPACKED}/app.asar" \
  "${UNPACKED}/backend/xcagi-backend.exe" \
  "${UNPACKED}/product-sku.json"; do
  if [[ ! -f "${required}" ]]; then
    echo "[err] packaged Windows release missing required file: ${required}" >&2
    exit 1
  fi
done

node scripts/package/generate-update-metadata.mjs "${FINAL}" "${VERSION}" win

echo "[ok] Windows installer: ${FINAL}"
