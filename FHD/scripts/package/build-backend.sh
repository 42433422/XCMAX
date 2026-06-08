#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-7.0.0}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  (cd frontend && [ -d node_modules ] || npm install)
  case "${XCAGI_PRODUCT_SKU:-}" in
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

python -m pip install --upgrade pip
RUNTIME_REQUIREMENTS="$(mktemp)"
grep -Ev '^[[:space:]]*pytest($|[-=<>])' XCAGI/requirements.txt > "${RUNTIME_REQUIREMENTS}"
python -m pip install -r "${RUNTIME_REQUIREMENTS}"
python -m pip install "pyinstaller>=6.0" appdirs

export XCAGI_VERSION="${VERSION}"
mkdir -p release
printf '%s\n' "${VERSION}" > release/VERSION
python -m PyInstaller --noconfirm --clean scripts/package/xcagi_backend.spec

echo "Backend build complete: dist/xcagi-backend"
