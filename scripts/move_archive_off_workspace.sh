#!/usr/bin/env bash
# 将 XCMAX/_archive 迁出工作区（尽调交付 <5GB 工作区）
set -euo pipefail

XCMAX_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARCHIVE_SRC="${XCMAX_ROOT}/_archive"
DEST_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}"
DEST="${DEST_ROOT}/xcmax-archive-202606"
MANIFEST="${DEST_ROOT}/MANIFEST.txt"

if [[ ! -d "$ARCHIVE_SRC" ]]; then
  echo "No _archive at $ARCHIVE_SRC (already moved or absent)."
  exit 0
fi

mkdir -p "$DEST_ROOT"
echo "Moving $ARCHIVE_SRC -> $DEST ..."
mv "$ARCHIVE_SRC" "$DEST"
(
  cd "$DEST_ROOT"
  if command -v shasum >/dev/null 2>&1; then
    find "$(basename "$DEST")" -type f 2>/dev/null | head -5000 | xargs shasum -a 256 2>/dev/null || true
  fi
) >>"$MANIFEST" 2>&1 || true
echo "Done. Update due-diligence zip to exclude $DEST"
