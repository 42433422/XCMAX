#!/usr/bin/env bash
# 校验 P-S 企业演示号是否能在指定修茈市场登录（默认官网 xiu-ci.com）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY="${FHD_ROOT}/.venv/bin/python"
[[ -x "${PY}" ]] || PY="python3"

exec "${PY}" "${SCRIPT_DIR}/verify_surface_audit_demo_market.py" "$@"
