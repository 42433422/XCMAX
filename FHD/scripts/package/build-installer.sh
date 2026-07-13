#!/usr/bin/env bash
# macOS：产品版本用于发布路径/制品名，三段工具链版本用于 npm/Electron。
set -euo pipefail

VERSION="${1:-1.0.0.0}"
SKU="${2:-}"
VERSION="${VERSION#FHD/}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
# workflow_dispatch on branch can leave ref_name=main; never feed that to npm version
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
  echo "[warn] invalid VERSION='${VERSION}', falling back to 1.0.0.0" >&2
  VERSION="1.0.0.0"
fi
TOOLCHAIN_VERSION="$(printf '%s' "${VERSION}" | cut -d. -f1-3)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
if [ -z "${PYTHON:-}" ] && [ -x "${ROOT}/.venv/bin/python" ]; then
  export PYTHON="${ROOT}/.venv/bin/python"
fi

MAC_SIGNING_ENV="${ROOT}/scripts/package/mac-signing.env"
if [ -f "${MAC_SIGNING_ENV}" ]; then
  # Treat the local signing file as dotenv data, not shell source. Certificate names commonly
  # contain spaces and parentheses, and must not require executable shell quoting.
  while IFS='=' read -r key value || [ -n "${key:-}" ]; do
    key="${key%%[[:space:]]*}"
    case "${key}" in
      "" | \#*) continue ;;
    esac
    export "${key}=${value}"
  done < "${MAC_SIGNING_ENV}"
  if [ -n "${CSC_NAME:-}" ]; then
    # electron-builder 26 selects the certificate class itself and rejects this prefix.
    CSC_NAME="${CSC_NAME#Developer ID Application: }"
    export CSC_NAME
  fi
  if [ -n "${CSC_LINK:-}" ] && [ -z "${CSC_KEY_PASSWORD:-}" ] && command -v security >/dev/null 2>&1; then
    # Prefer an already unlocked keychain identity when the local P12 has no configured password.
    # CI normally provides CSC_KEY_PASSWORD and continues to use CSC_LINK.
    if security find-identity -v -p codesigning 2>/dev/null | grep -Fq "${CSC_NAME:-}"; then
      unset CSC_LINK
    fi
  fi
  if [ -n "${XCAGI_UPDATE_ED25519_PRIVATE_KEY_FILE:-}" ] && [ -f "${XCAGI_UPDATE_ED25519_PRIVATE_KEY_FILE}" ]; then
    export XCAGI_UPDATE_ED25519_PRIVATE_KEY="$(cat "${XCAGI_UPDATE_ED25519_PRIVATE_KEY_FILE}")"
  fi
fi

sku_label() {
  case "$1" in
    personal) echo Personal ;;
    enterprise) echo Enterprise ;;
    *) echo "Unknown SKU: $1" >&2; exit 1 ;;
  esac
}

sku_app_id() {
  case "$1" in
    personal) echo com.xcagi.desktop.personal ;;
    enterprise) echo com.xcagi.desktop.enterprise ;;
    *) echo "Unknown SKU: $1" >&2; exit 1 ;;
  esac
}

sku_update_url() {
  case "$1" in
    personal) echo https://xiu-ci.com/releases/stable/personal/ ;;
    enterprise) echo https://xiu-ci.com/releases/stable/enterprise/ ;;
    *) echo "Unknown SKU: $1" >&2; exit 1 ;;
  esac
}

build_one_sku() {
  local sku="$1"
  local label
  label="$(sku_label "$sku")"
  local out_dir="${ROOT}/release/xcagi-v${VERSION}/${sku}"
  mkdir -p "${out_dir}"

  echo "========== Building macOS SKU: ${sku} =========="
  if [ "${SKIP_BACKEND:-0}" != "1" ]; then
    XCAGI_PRODUCT_SKU="${sku}" scripts/package/build-backend.sh "${VERSION}"
  else
    "${PYTHON:-python3}" -m pip install "Pillow>=10.2.0" -q
  fi

  printf '{"sku":"%s","schema_version":1}\n' "${sku}" > desktop/resources/product-sku.json
  "${PYTHON:-python3}" scripts/package/generate-desktop-resources.py

  (cd desktop && [ -d node_modules ] || npm install)
  (cd desktop && npm version "${TOOLCHAIN_VERSION}" --no-git-tag-version --allow-same-version)
  (cd desktop && npm run build)
  local artifact_name="XCAGI-${label}-${VERSION}-mac-\${arch}.\${ext}"
  (cd desktop && npx electron-builder --mac dmg zip --publish never \
    "--config.directories.output=../release/xcagi-v${VERSION}/${sku}" \
    "--config.artifactName=${artifact_name}" \
    "--config.appId=$(sku_app_id "$sku")" \
    "--config.publish.url=$(sku_update_url "$sku")" \
    "--config.extraMetadata.productSku=${sku}")

  local artifact
  artifact="$(find "${out_dir}" -type f \( -name "*.dmg" -o -name "XCAGI-${label}-*.dmg" \) -print 2>/dev/null | sort | tail -n 1 || true)"
  if [ -n "${artifact}" ]; then
    XCAGI_PRODUCT_VERSION="${VERSION}" \
      node scripts/package/generate-update-metadata.mjs "${artifact}" "${TOOLCHAIN_VERSION}" mac
  fi
  echo "Done: ${out_dir}/"
}

if [ -z "${SKU}" ]; then
  echo "Usage: $0 <version> <personal|enterprise>"
  echo "   or: $0 <version> all"
  exit 1
fi

if [ "${SKU}" = "all" ]; then
  mkdir -p "${ROOT}/release/xcagi-v${VERSION}"/{personal,enterprise}
  for s in personal enterprise; do
    build_one_sku "${s}"
  done
  echo "Both macOS SKUs under release/xcagi-v${VERSION}/"
else
  case "${SKU}" in
    personal|enterprise) build_one_sku "${SKU}" ;;
    *) echo "Invalid SKU: ${SKU}" >&2; exit 1 ;;
  esac
fi
