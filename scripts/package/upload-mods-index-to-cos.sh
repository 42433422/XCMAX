#!/usr/bin/env bash
# Upload mods-index.json to COS (optional P6). Requires coscmd or coscli on deploy host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INDEX="${MODS_INDEX_PATH:-}"
if [ -z "$INDEX" ]; then
  for candidate in "$ROOT/mods/mods-index.json" "$ROOT/resources/mods_index.json"; do
    if [ -f "$candidate" ]; then
      INDEX="$candidate"
      break
    fi
  done
fi

if [ -z "$INDEX" ] || [ ! -f "$INDEX" ]; then
  echo "[err] mods-index.json not found (set MODS_INDEX_PATH)"
  exit 1
fi

BUCKET="${COS_BUCKET:-}"
PREFIX="${COS_PREFIX:-xcagi}"
REGION="${COS_REGION:-ap-guangzhou}"
if [ -z "$BUCKET" ]; then
  echo "[err] COS_BUCKET required"
  exit 1
fi

REMOTE_KEY="${PREFIX%/}/mods/mods-index.json"
echo "[upload] $INDEX -> cos://${BUCKET}/${REMOTE_KEY}"

if command -v coscmd >/dev/null 2>&1; then
  coscmd -b "$BUCKET" -r "$REGION" upload "$INDEX" "$REMOTE_KEY"
elif command -v coscli >/dev/null 2>&1; then
  coscli cp "$INDEX" "cos://${BUCKET}/${REMOTE_KEY}"
else
  echo "[err] install coscmd or coscli on deploy host"
  exit 1
fi

echo "[ok] mods index uploaded"
