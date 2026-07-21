#!/usr/bin/env bash
# 独立验证 FHD staging 真实可用性（不依赖 prod /fhd-api）。
set -euo pipefail
PUBLIC_URL="${FHD_STAGING_HEALTH_URL:-https://xiu-ci.com/fhd-staging-api/api/health}"
LOCAL_URL="${FHD_STAGING_LOCAL_HEALTH_URL:-http://127.0.0.1:5101/api/health}"
TIMEOUT="${FHD_STAGING_HEALTH_TIMEOUT:-8}"
CHECK_LOCAL=0
CHECK_SSH=0
HOST="${FHD_PUSH_HOST:-119.27.178.147}"
USER="${FHD_PUSH_USER:-root}"

usage() { echo "Usage: check-staging-health.sh [--local] [--ssh]"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) CHECK_LOCAL=1; shift ;;
    --ssh) CHECK_SSH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[staging-health] unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

fail=0
check_url() {
  local label="$1" url="$2" body
  if body=$(curl --noproxy '*' -fsS --max-time "$TIMEOUT" "$url"); then
    echo "[staging-health] OK  $label -> $url"
    echo "  body: $(printf '%s' "$body" | head -c 200)"
  else
    echo "[staging-health] FAIL $label -> $url" >&2
    fail=1
  fi
}
check_url "public" "$PUBLIC_URL"
if [[ "$CHECK_LOCAL" == 1 ]]; then check_url "local" "$LOCAL_URL"; fi
if [[ "$CHECK_SSH" == 1 ]]; then
  if ssh -o BatchMode=yes -o ConnectTimeout=8 "${USER}@${HOST}" \
      "curl --noproxy '*' -fsS --max-time 5 '$LOCAL_URL'"; then
    echo "[staging-health] OK  ssh-local -> ${USER}@${HOST} $LOCAL_URL"
  else
    echo "[staging-health] FAIL ssh-local -> ${USER}@${HOST} $LOCAL_URL" >&2
    fail=1
  fi
fi
if [[ "$fail" != 0 ]]; then
  echo "[staging-health] staging unavailable" >&2
  exit 1
fi
echo "[staging-health] staging healthy"
