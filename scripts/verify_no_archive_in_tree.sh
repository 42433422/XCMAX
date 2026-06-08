#!/usr/bin/env bash
# PR 门禁：禁止 _archive/ 出现在工作区（尽调卫生）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -d "${ROOT}/_archive" ]]; then
  SIZE=$(du -sh "${ROOT}/_archive" 2>/dev/null | cut -f1)
  echo "ERROR: _archive/ must not live in workspace (found ${SIZE})."
  echo "Run: bash FHD/scripts/move_archive_off_workspace.sh"
  echo "See: ARCHIVE_POINTER.md"
  exit 1
fi
echo "OK: no _archive/ in workspace"
