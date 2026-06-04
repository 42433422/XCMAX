#!/usr/bin/env bash
# macOS: codesign + optional notarization gate (full notarize via desktop/build/notarize.cjs)
set -euo pipefail

ARTIFACT="${1:?usage: sign-artifact.sh <path-to-app-or-dmg>}"
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"

if [[ -z "${IDENTITY}" ]]; then
  echo "[sign] APPLE_SIGNING_IDENTITY unset; skipping codesign for ${ARTIFACT}"
  exit 0
fi

if [[ -d "${ARTIFACT}" ]]; then
  codesign --force --deep --options runtime --sign "${IDENTITY}" "${ARTIFACT}"
  codesign --verify --deep --strict "${ARTIFACT}"
else
  echo "[sign] Expected .app bundle directory; got file (use electron-builder afterSign for dmg)"
  exit 1
fi
echo "[sign] OK"
