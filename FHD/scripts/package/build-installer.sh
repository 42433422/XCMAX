#!/usr/bin/env bash
# macOS：产品版本用于发布路径/制品名，三段工具链版本用于 npm/Electron。
set -euo pipefail

VERSION="${1:-1.0.0.1}"
SKU="${2:-}"
VERSION="${VERSION#FHD/}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
# workflow_dispatch on branch can leave ref_name=main; never feed that to npm version
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
  echo "[warn] invalid VERSION='${VERSION}', falling back to 1.0.0.1" >&2
  VERSION="1.0.0.1"
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
fi

# Apply signing normalization to both the local dotenv path and callers that
# inject the same values through CI or a clean release worktree environment.
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
  # Desktop/iCloud FileProvider can continuously re-attach FinderInfo xattrs to
  # an app bundle under the checkout, which makes codesign reject nested
  # helpers. Sign and assemble outside FileProvider, then copy sealed artifacts
  # back to the release directory.
  local package_stage="${TMPDIR:-/tmp}/xcagi-electron-builder-${VERSION}-${sku}"
  mkdir -p "${out_dir}"
  rm -rf "${package_stage}"
  mkdir -p "${package_stage}"

  echo "========== Building macOS SKU: ${sku} =========="
  if [ "${SKIP_BACKEND:-0}" != "1" ]; then
    XCAGI_PRODUCT_SKU="${sku}" scripts/package/build-backend.sh "${VERSION}"
  else
    if ! "${PYTHON:-python3}" -m pip --version >/dev/null 2>&1; then
      "${PYTHON:-python3}" -m ensurepip --upgrade
    fi
    "${PYTHON:-python3}" -m pip install "Pillow>=10.2.0" -q
  fi

  printf '{"sku":"%s","schema_version":1}\n' "${sku}" > desktop/resources/product-sku.json
  local build_sha
  build_sha="$("${PYTHON:-python3}" scripts/package/generate-desktop-build-info.py --version "${VERSION}")"
  export XCAGI_BUILD_SHA="${build_sha}"
  "${PYTHON:-python3}" scripts/package/generate-desktop-resources.py

  (cd desktop && [ -d node_modules ] || npm install)
  # Finder/provenance xattrs can survive npm's Electron extraction and make
  # codesign reject helper binaries as containing resource-fork detritus.
  if command -v xattr >/dev/null 2>&1; then
    xattr -cr desktop/node_modules/electron/dist
  fi
  (cd desktop && npm version "${TOOLCHAIN_VERSION}" --no-git-tag-version --allow-same-version)
  if [ "${SKIP_DESKTOP_BUILD:-0}" != "1" ]; then
    (cd desktop && npm run build)
  elif [ ! -f desktop/dist/main.js ]; then
    echo "[err] SKIP_DESKTOP_BUILD=1 but desktop/dist/main.js is missing" >&2
    exit 1
  else
    cp desktop/resources/splash.html desktop/dist/splash.html
  fi
  local artifact_name="XCAGI-${label}-${VERSION}-mac-\${arch}.\${ext}"
  # electron-builder's DMG target downloads an optional dmg-builder bundle at
  # release time. Produce the updater ZIP here, then use macOS' built-in
  # hdiutil for the DMG so an unrelated CDN timeout cannot discard a signed,
  # notarized application build.
  local package_attempt
  local package_ok=0
  for package_attempt in 1 2 3; do
    if (cd desktop && PATH="${ROOT}/scripts/package/codesign-retry-bin:${PATH}" npx electron-builder --mac zip --publish never \
      "--config.electronDist=node_modules/electron/dist" \
      "--config.directories.output=${package_stage}" \
      "--config.artifactName=${artifact_name}" \
      "--config.appId=$(sku_app_id "$sku")" \
      "--config.publish.url=$(sku_update_url "$sku")" \
      "--config.extraMetadata.productSku=${sku}"); then
      package_ok=1
      break
    fi
    if [ "${package_attempt}" -lt 3 ]; then
      echo "[warn] macOS signing/package attempt ${package_attempt}/3 failed; retrying after Apple timestamp service cooldown" >&2
      sleep $((package_attempt * 8))
    fi
  done
  if [ "${package_ok}" != "1" ]; then
    echo "[err] macOS signing/package failed after 3 attempts" >&2
    exit 1
  fi
  local app_path="${package_stage}/mac-arm64/XCAGI.app"
  if [ ! -d "${app_path}" ]; then
    app_path="$(find "${package_stage}" -maxdepth 2 -type d -name 'XCAGI.app' -print | head -n 1 || true)"
  fi
  if [ -z "${app_path}" ] || [ ! -d "${app_path}" ]; then
    echo "[err] signed macOS application was not produced in ${package_stage}" >&2
    exit 1
  fi
  local artifact_arch
  case "$(uname -m)" in
    arm64) artifact_arch="arm64" ;;
    x86_64) artifact_arch="x64" ;;
    *) artifact_arch="$(uname -m)" ;;
  esac
  # Volume names with spaces make hdiutil fail with "操作不被允许" on some macOS hosts.
  scripts/package/create-mac-dmg.sh \
    "${app_path}" \
    "${package_stage}/XCAGI-${label}-${VERSION}-mac-${artifact_arch}.dmg" \
    "XCAGI-${label}"
  # Publish only sealed archive artifacts. A loose .app copied back into this
  # Desktop/FileProvider checkout receives com.apple.FinderInfo again almost
  # immediately, which makes codesign reject that copy even though the ZIP and
  # DMG produced from the external staging directory remain valid.
  local staged_file
  for staged_file in "${package_stage}"/*; do
    if [ -f "${staged_file}" ]; then
      ditto --norsrc "${staged_file}" "${out_dir}/$(basename "${staged_file}")"
    fi
  done
  rm -rf "${package_stage}"

  # electron-updater's macOS differential updater consumes the ZIP artifact.
  # A DMG-only latest-mac.yml downloads successfully in a browser but fails in
  # the app with "ZIP file not provided".  Treat a missing ZIP as a release
  # failure instead of publishing a feed that can never be installed.
  local update_artifact
  update_artifact="$(find "${out_dir}" -maxdepth 1 -type f -name "XCAGI-${label}-${VERSION}-mac-*.zip" -print 2>/dev/null | sort | tail -n 1 || true)"
  if [ -z "${update_artifact}" ]; then
    echo "[err] macOS auto-update ZIP was not produced in ${out_dir}" >&2
    exit 1
  fi
  XCAGI_PRODUCT_VERSION="${VERSION}" \
    node scripts/package/generate-update-metadata.mjs "${update_artifact}" "${TOOLCHAIN_VERSION}" mac
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
