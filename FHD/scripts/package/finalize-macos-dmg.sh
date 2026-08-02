#!/usr/bin/env bash
# Submit the outer DMG to Apple, staple the ticket, then refresh every file
# derived from the DMG bytes. The app bundle is notarized by electron-builder's
# afterSign hook; this script closes the separate outer-container gate.
set -euo pipefail

DMG_PATH="${1:?Usage: $0 <dmg-path> <product-version> [toolchain-version]}"
PRODUCT_VERSION="${2:?Usage: $0 <dmg-path> <product-version> [toolchain-version]}"
TOOLCHAIN_VERSION="${3:-$(printf '%s' "${PRODUCT_VERSION}" | cut -d. -f1-3)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${DMG_PATH}" != /* ]]; then
  DMG_PATH="$(cd "$(dirname "${DMG_PATH}")" && pwd)/$(basename "${DMG_PATH}")"
fi
test -f "${DMG_PATH}"

for required in \
  APP_STORE_CONNECT_API_KEY_ID \
  APP_STORE_CONNECT_API_ISSUER_ID \
  APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64; do
  if [ -z "${!required:-}" ]; then
    echo "::error::${required} is required to notarize the release DMG"
    exit 1
  fi
done

key_dir="$(mktemp -d)"
cleanup() {
  rm -rf "${key_dir}"
}
trap cleanup EXIT
key_path="${key_dir}/AuthKey_${APP_STORE_CONNECT_API_KEY_ID}.p8"

python3 - "${key_path}" <<'PY'
import base64
import os
import sys
from pathlib import Path

encoded = "".join(os.environ["APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64"].split())
Path(sys.argv[1]).write_bytes(base64.b64decode(encoded, validate=True))
PY
chmod 600 "${key_path}"

echo "Submitting outer DMG for Apple notarization: ${DMG_PATH}"
xcrun notarytool submit "${DMG_PATH}" \
  --key "${key_path}" \
  --key-id "${APP_STORE_CONNECT_API_KEY_ID}" \
  --issuer "${APP_STORE_CONNECT_API_ISSUER_ID}" \
  --wait \
  --timeout 30m
xcrun stapler staple "${DMG_PATH}"
xcrun stapler validate "${DMG_PATH}"
spctl -a -vv -t open --context context:primary-signature "${DMG_PATH}"

# Stapling changes the DMG bytes. Rebuild the companion blockmap only.
# Do NOT regenerate latest-mac.yml from the DMG — electron-updater on macOS
# requires a ZIP feed (see generate-update-metadata.mjs). ZIP metadata is
# produced earlier by build-installer.sh and must stay ZIP-based.
cd "${ROOT}"
# electron-builder 26+ removed util/appBuilder; use in-tree buildBlockMap (gzip sidecar).
node - "${DMG_PATH}" <<'NODE'
const { buildBlockMap } = require('./desktop/node_modules/app-builder-lib/out/targets/blockmap/blockmap')

const dmg = process.argv[2]
buildBlockMap(dmg, 'gzip', `${dmg}.blockmap`)
  .then(info => console.log(`Refreshed DMG blockmap: size=${info.size} sha512=${info.sha512}`))
  .catch(error => {
    console.error(error)
    process.exit(1)
  })
NODE

echo "Finalized notarized DMG (ZIP update feed left untouched): ${DMG_PATH}"
