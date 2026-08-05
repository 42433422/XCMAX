#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-1.0.0.0}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-}"
case "${PRODUCT_SKU}" in
  "" | personal | enterprise) ;;
  *)
    echo "[err] XCAGI_PRODUCT_SKU must be personal or enterprise, current: ${PRODUCT_SKU}" >&2
    exit 1
    ;;
esac

if [[ -n "${PRODUCT_SKU}" ]]; then
  bash scripts/package/stage-bundled-mods.sh "${PRODUCT_SKU}"
  bash scripts/package/stage-industry-seeds.sh "${PRODUCT_SKU}"
  mkdir -p build
  printf '{"sku":"%s","schema_version":1}\n' "${PRODUCT_SKU}" > build/product-sku.json
fi

# 前端唯一构建：templates/vue-dist 是 Web 与桌面端共享的 SSOT 产物。
# 默认不重建（复用已由 build-frontend.sh 产出的那份，避免从 dirty 工作区静默重建导致漂移/回退）；
# 仅当产物缺失、或显式 FHD_REBUILD_FRONTEND=1 时才重建。CI 桌面包应传入 SKIP_FRONTEND=1 直接复用。
if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  if [ "${FHD_USE_PREBUILT_VUE_DIST:-1}" = "1" ] && [ -f "templates/vue-dist/index.html" ]; then
    echo "[info] 复用已有 templates/vue-dist（$(grep -oE 'index-[A-Za-z0-9_-]+\.js' templates/vue-dist/index.html | head -1 || echo 'unknown')）—— 如需重建请设 FHD_REBUILD_FRONTEND=1"
  elif [ "${FHD_REBUILD_FRONTEND:-0}" = "1" ] || [ ! -f "templates/vue-dist/index.html" ]; then
    bash scripts/package/build-frontend.sh "${PRODUCT_SKU:-generic}"
  fi
  # 桌面包不构建 admin-console（管理端仅网页；进程级 is_desktop_mode 禁 /admin）
fi

if [ -z "${PYTHON:-}" ] && [ -x "${ROOT}/.venv/bin/python" ]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

# uv-managed virtual environments may intentionally omit pip.  PyInstaller's
# editable dependency install still uses pip, so bootstrap it deterministically
# instead of failing after the (expensive) frontend build has completed.
if ! "${PYTHON}" -m pip --version >/dev/null 2>&1; then
  "${PYTHON}" -m ensurepip --upgrade
fi
"${PYTHON}" -m pip install --upgrade pip
"${PYTHON}" -m pip install -e ".[server-api]"
"${PYTHON}" -m pip install "pyinstaller>=6.0" appdirs

if [[ "$(uname -s)" == "Darwin" ]]; then
  bash scripts/package/normalize-macos-python-binaries.sh "${PYTHON}"
fi

export XCAGI_VERSION="${VERSION}"
if [[ -n "${PRODUCT_SKU}" ]]; then
  export XCAGI_PRODUCT_SKU="${PRODUCT_SKU}"
  export XCAGI_STAGED_MODS_DIR="${ROOT}/build/staged-mods-${PRODUCT_SKU}"
  export XCAGI_MODS_ROOT="${XCAGI_STAGED_MODS_DIR}"
  if [[ -d "${ROOT}/build/staged-industry-seeds-${PRODUCT_SKU}" ]]; then
    export XCAGI_STAGED_INDUSTRY_SEEDS_DIR="${ROOT}/build/staged-industry-seeds-${PRODUCT_SKU}"
  fi
  "${PYTHON}" scripts/package/generate_mods_index.py
fi
mkdir -p release
printf '%s\n' "${VERSION}" > release/VERSION
"${PYTHON}" -m PyInstaller --noconfirm --clean scripts/package/xcagi_backend.spec

echo "Backend build complete: dist/xcagi-backend"
