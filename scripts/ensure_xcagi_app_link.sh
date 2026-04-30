#!/usr/bin/env bash
# Creates XCAGI/app -> ../app symlink for IDE navigation. Ignored by XCAGI/.gitignore (/app).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
XCAGI="$ROOT/XCAGI"
TARGET="$ROOT/app"
LINK="$XCAGI/app"
if [[ ! -d "$TARGET" ]]; then
  echo "Missing $TARGET" >&2
  exit 1
fi
if [[ ! -d "$XCAGI" ]]; then
  echo "Missing $XCAGI" >&2
  exit 1
fi
rm -rf "$LINK"
ln -s "../app" "$LINK"
echo "OK: $LINK -> ../app"
