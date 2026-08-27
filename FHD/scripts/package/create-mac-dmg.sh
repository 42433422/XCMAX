#!/usr/bin/env bash
# Build a release DMG with macOS' built-in tools so packaging does not depend
# on electron-builder downloading the optional dmg-builder bundle at runtime.
set -euo pipefail

APP_PATH="${1:-}"
DMG_PATH="${2:-}"
VOLUME_NAME="${3:-XCAGI}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CODESIGN_BIN="${ROOT}/scripts/package/codesign-retry-bin/codesign"

if [ -z "${APP_PATH}" ] || [ -z "${DMG_PATH}" ]; then
  echo "Usage: $0 <XCAGI.app> <output.dmg> [volume-name]" >&2
  exit 2
fi
if [ "$(uname -s)" != "Darwin" ]; then
  echo "[err] macOS DMG creation requires Darwin" >&2
  exit 1
fi
if [ ! -d "${APP_PATH}" ]; then
  echo "[err] app bundle not found: ${APP_PATH}" >&2
  exit 1
fi

# Standalone use should have the same credentials as build-installer.sh. Read
# the dotenv file as data because certificate names contain spaces/parentheses.
MAC_SIGNING_ENV="${ROOT}/scripts/package/mac-signing.env"
if [ -f "${MAC_SIGNING_ENV}" ]; then
  while IFS='=' read -r key value || [ -n "${key:-}" ]; do
    key="${key%%[[:space:]]*}"
    case "${key}" in
      "" | \#*) continue ;;
    esac
    if [ -z "${!key:-}" ]; then
      export "${key}=${value}"
    fi
  done < "${MAC_SIGNING_ENV}"
fi

find_developer_id_identity() {
  local configured="${CSC_NAME:-}"
  local identities
  identities="$(security find-identity -v -p codesigning 2>/dev/null || true)"

  if [[ "${configured}" == "Developer ID Application:"* ]] && \
    grep -Fq "\"${configured}\"" <<< "${identities}"; then
    printf '%s\n' "${configured}"
    return 0
  fi

  local configured_suffix="${configured#Developer ID Application: }"
  local match
  match="$(printf '%s\n' "${identities}" | \
    sed -n 's/.*"\(Developer ID Application:.*\)"/\1/p' | \
    grep -F "${configured_suffix}" | head -n 1 || true)"
  if [ -n "${match}" ]; then
    printf '%s\n' "${match}"
    return 0
  fi

  match="$(printf '%s\n' "${identities}" | \
    sed -n 's/.*"\(Developer ID Application:.*\)"/\1/p' | head -n 1 || true)"
  [ -n "${match}" ] && printf '%s\n' "${match}"
}

notarize_dmg() {
  local dmg="$1"
  local api_key_path="${APP_STORE_CONNECT_API_KEY_PATH:-}"
  local api_key_id="${APP_STORE_CONNECT_API_KEY_ID:-}"
  local api_issuer="${APP_STORE_CONNECT_API_ISSUER_ID:-}"
  local apple_id="${APPLE_ID:-}"
  local apple_password="${APPLE_APP_SPECIFIC_PASSWORD:-${APPLE_ID_PASSWORD:-}}"
  local team_id="${APPLE_TEAM_ID:-${IOS_TEAM_ID:-}}"
  local result_file="$2"

  if [ "${XCAGI_LOCAL_ACCEPTANCE_BUILD:-0}" = "1" ]; then
    if [ -n "${CI:-}" ]; then
      echo "[err] XCAGI_LOCAL_ACCEPTANCE_BUILD is forbidden in CI" >&2
      return 1
    fi
    echo "[notarize] skipped for explicit local acceptance build"
    return 0
  fi

  # In CI, electron-builder's afterSign hook materializes the base64 secret at
  # this path before the DMG is assembled. Discover it when the workflow does
  # not provide APP_STORE_CONNECT_API_KEY_PATH explicitly.
  if [ -n "${api_key_id}" ] && { [ -z "${api_key_path}" ] || [ ! -f "${api_key_path}" ]; }; then
    local candidate
    for candidate in \
      "${HOME}/.appstoreconnect/private_keys/AuthKey_${api_key_id}.p8" \
      "${HOME}/.config/xcagi/private_keys/AuthKey_${api_key_id}.p8" \
      "${HOME}/.config/xcagi/AuthKey_${api_key_id}.p8"; do
      if [ -f "${candidate}" ]; then
        api_key_path="${candidate}"
        break
      fi
    done
  fi

  if [ -n "${api_key_path}" ] && [ -f "${api_key_path}" ] && \
    [ -n "${api_key_id}" ] && [ -n "${api_issuer}" ]; then
    echo "[notarize] submitting DMG with App Store Connect API key"
    xcrun notarytool submit "${dmg}" \
      --key "${api_key_path}" \
      --key-id "${api_key_id}" \
      --issuer "${api_issuer}" \
      --wait --timeout 60m --output-format json > "${result_file}"
  elif [ -n "${apple_id}" ] && [ -n "${apple_password}" ] && [ -n "${team_id}" ]; then
    echo "[notarize] submitting DMG with Apple ID"
    xcrun notarytool submit "${dmg}" \
      --apple-id "${apple_id}" \
      --password "${apple_password}" \
      --team-id "${team_id}" \
      --wait --timeout 60m --output-format json > "${result_file}"
  elif [ -n "${CI:-}" ]; then
    echo "[err] CI release requires Apple notarization credentials" >&2
    return 1
  else
    echo "[notarize] skipped: no Apple notarization credentials configured"
    return 0
  fi

  local status
  status="$(python3 - "${result_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle).get("status", ""))
PY
)"
  if [ "${status}" != "Accepted" ]; then
    echo "[err] Apple notarization status is '${status:-unknown}'" >&2
    return 1
  fi
  echo "[notarize] DMG accepted"
  xcrun stapler staple "${dmg}"
  xcrun stapler validate "${dmg}"
}

DMG_PATH="$(cd "$(dirname "${DMG_PATH}")" && pwd)/$(basename "${DMG_PATH}")"
DMG_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/xcagi-dmg-root.XXXXXX")"
NOTARY_RESULT="$(mktemp "${TMPDIR:-/tmp}/xcagi-dmg-notary.XXXXXX.json")"
cleanup() {
  rm -rf "${DMG_ROOT}" "${NOTARY_RESULT}"
}
trap cleanup EXIT

rm -f "${DMG_PATH}"
# iCloud/Desktop FileProvider can re-attach com.apple.provenance / FinderInfo
# xattrs to the app bundle, which makes hdiutil reject it with "操作不被允许 /
# operation not permitted". Strip them on the staged copy before assembling.
if command -v xattr >/dev/null 2>&1; then
  xattr -cr "${APP_PATH}" 2>/dev/null || true
fi
ditto --norsrc "${APP_PATH}" "${DMG_ROOT}/$(basename "${APP_PATH}")"
if command -v xattr >/dev/null 2>&1; then
  xattr -cr "${DMG_ROOT}/$(basename "${APP_PATH}")" 2>/dev/null || true
fi
ln -s /Applications "${DMG_ROOT}/Applications"
hdiutil create \
  -volname "${VOLUME_NAME}" \
  -srcfolder "${DMG_ROOT}" \
  -ov -format UDZO \
  "${DMG_PATH}"

SIGNING_IDENTITY="$(find_developer_id_identity || true)"
if [ -n "${SIGNING_IDENTITY}" ]; then
  echo "[sign] signing DMG with ${SIGNING_IDENTITY}"
  "${CODESIGN_BIN}" --force --timestamp --sign "${SIGNING_IDENTITY}" "${DMG_PATH}"
  "${CODESIGN_BIN}" --verify --strict --verbose=2 "${DMG_PATH}"
elif [ -n "${CI:-}" ]; then
  echo "[err] CI release requires a Developer ID Application identity" >&2
  exit 1
else
  echo "[sign] skipped: no Developer ID Application identity found"
fi

notarize_dmg "${DMG_PATH}" "${NOTARY_RESULT}"
hdiutil verify "${DMG_PATH}"
echo "Created: ${DMG_PATH}"
