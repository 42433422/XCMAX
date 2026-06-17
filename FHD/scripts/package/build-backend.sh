#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-10.0.0}"
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

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  (cd frontend && [ -d node_modules ] || npm install)
  case "${PRODUCT_SKU}" in
    personal)
      (cd frontend && npm run build:minimal)
      ;;
    enterprise)
      (cd frontend && VITE_XCAGI_PRODUCT_SKU=enterprise npm run build)
      ;;
    *)
      (cd frontend && npm run build)
      ;;
  esac
fi

PYTHON="${PYTHON:-python3}"

"${PYTHON}" -m pip install --upgrade pip
"${PYTHON}" -m pip install -e ".[server-api]"
"${PYTHON}" -m pip install "pyinstaller>=6.0" appdirs

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
