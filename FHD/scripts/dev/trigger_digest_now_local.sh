#!/usr/bin/env bash
# 立即触发本地 MODstore 日更摘要（等同 08:00 cron / digest-now）
# 用法：bash FHD/scripts/dev/trigger_digest_now_local.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY="${FHD_ROOT}/.venv/bin/python"
ENV_FILE="${FHD_ROOT}/XCAGI/.env.local-market"

log() { printf '[digest-now] %s\n' "$*"; }

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -v '^#' "${ENV_FILE}" | sed '/^\s*$/d')
  set +a
fi

export MODSTORE_DIGEST_HTTP_TIMEOUT_SEC="${MODSTORE_DIGEST_HTTP_TIMEOUT_SEC:-${MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC:-1800}}"
export PYTHONPATH="${FHD_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

log "触发 POST /api/admin/email/digest-now（超时最长 ${MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC:-1800}s，含三端巡检 + 员工大会）…"
"${PY}" - <<'PY'
import asyncio
import json
import sys

from app.application.digest_email_app_service import trigger_digest_now_local


async def main() -> None:
    result = await trigger_digest_now_local()
    print(json.dumps(result, ensure_ascii=False, indent=2))


try:
    asyncio.run(main())
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise
PY
log "完成"
