#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-7.0.0}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if [ "${SKIP_BACKEND:-0}" != "1" ]; then
  scripts/package/build-backend.sh "${VERSION}"
else
  python3 -m pip install "Pillow>=10.2.0" -q
fi

python3 scripts/package/generate-desktop-resources.py

(cd desktop && [ -d node_modules ] || npm install)
(cd desktop && npm version "${VERSION}" --no-git-tag-version)
(cd desktop && npm run dist:mac)

ARTIFACT="$(find release/desktop-designed-final2 -type f -name '*.dmg' -print | sort | tail -n 1 || true)"
if [ -n "${ARTIFACT}" ]; then
  node scripts/package/generate-update-metadata.mjs "${ARTIFACT}" "${VERSION}" mac
fi

echo "macOS installer build complete: release/desktop-designed-final2"
