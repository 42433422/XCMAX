#!/usr/bin/env bash
# 用 .deploy-ssh.local 中的密码/主机，同步 modstore_server 并重启 modstore
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/root/modstore-git/MODstore_deploy}"
LOCAL_ENV="${MARKET_DIR}/.deploy-ssh.local"

if [[ -f "${LOCAL_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_ENV}"
  set +a
fi

export DEPLOY_SSH_HOST="${DEPLOY_SSH_HOST:-119.27.178.147}"
export DEPLOY_SSH_USER="${DEPLOY_SSH_USER:-root}"
export DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22}"

is_public_ipv4() {
  local h="${1%%:*}"
  [[ "$h" =~ ^10\. ]] && return 1
  [[ "$h" =~ ^192\.168\. ]] && return 1
  [[ "$h" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]] && return 1
  [[ "$h" == "localhost" || "$h" == "127.0.0.1" ]] && return 1
  [[ "$h" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && return 0
  return 1
}
if [[ "${DEPLOY_ALLOW_PUBLIC:-}" != "1" ]] && is_public_ipv4 "${DEPLOY_SSH_HOST}"; then
  echo "[err] 公网部署请设置 DEPLOY_ALLOW_PUBLIC=1" >&2
  exit 3
fi

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "[err] 请在 ${LOCAL_ENV} 中设置 DEPLOY_SSH_PASSWORD" >&2
  exit 2
fi

MODSTORE_LOCAL="$(cd "${MARKET_DIR}/../modstore_server" && pwd)"
TAR="/tmp/modstore_server-deploy-$$.tgz"
trap 'rm -f "${TAR}"' EXIT

echo "[pack] ${MODSTORE_LOCAL} → ${TAR}"
tar -C "$(dirname "${MODSTORE_LOCAL}")" -czf "${TAR}" "$(basename "${MODSTORE_LOCAL}")"

export DEPLOY_TAR="${TAR}"
export DEPLOY_ROOT
/usr/bin/expect -f "${SCRIPT_DIR}/ssh-push-backend.expect"
echo "[ok] modstore_server 已同步并重启 modstore"
