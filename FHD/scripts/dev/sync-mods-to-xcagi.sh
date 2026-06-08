#!/usr/bin/env bash
# 便捷入口：FHD/mods（SSOT）→ FHD/XCAGI/mods（导出副本）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
exec python3 "${SCRIPT_DIR}/mods_ssot.py" sync "$@"
