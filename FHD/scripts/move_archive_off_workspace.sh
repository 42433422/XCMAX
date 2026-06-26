#!/usr/bin/env bash
# Move root-level _archive out of the checked-out workspace.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARCHIVE_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}"
TARGET="${ARCHIVE_ROOT}/xcmax-archive-202606"

if [[ ! -d "${ROOT}/_archive" ]]; then
  echo "OK: no root _archive/ in workspace"
  exit 0
fi

mkdir -p "${TARGET}"
rsync -a "${ROOT}/_archive/" "${TARGET}/"
rm -rf "${ROOT}/_archive"
echo "Moved root _archive/ to ${TARGET}/"
