#!/usr/bin/env bash
set -euo pipefail
FHD_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$FHD_ROOT"
exec bash "$FHD_ROOT/scripts/health-check.sh" "$@"
