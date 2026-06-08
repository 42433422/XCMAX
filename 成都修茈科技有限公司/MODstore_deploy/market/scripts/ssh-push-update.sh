#!/usr/bin/env bash
# SSH 推送 market/dist 到生产（密码或私钥，同步两个远端 dist 目录）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
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
  echo "[err] 默认不走公网 SSH（当前 DEPLOY_SSH_HOST=${DEPLOY_SSH_HOST}）。" >&2
  echo "  内网/机内: ./scripts/deploy-internal.sh" >&2
  echo "  VPC 内网: 在 .deploy-ssh.local 设置 DEPLOY_SSH_HOST=10.x.x.x 后再运行本脚本" >&2
  echo "  确需公网: DEPLOY_ALLOW_PUBLIC=1 $0" >&2
  exit 3
fi
export DEPLOY_REMOTE_DIST="${DEPLOY_REMOTE_DIST:-/root/成都修茈科技有限公司/MODstore_deploy/market/dist}"
export DEPLOY_REMOTE_DIST_EXTRA="${DEPLOY_REMOTE_DIST_EXTRA:-/root/modstore-git/MODstore_deploy/market/dist}"

cd "${MARKET_DIR}"

if [[ ! -f dist/index.html ]]; then
  echo "[build] dist 缺失，正在构建…"
  ./scripts/build-dist.sh
fi

echo "[info] 目标 ${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}:${DEPLOY_SSH_PORT}"
echo "[info] 远端目录:"
echo "       ${DEPLOY_REMOTE_DIST}"
echo "       ${DEPLOY_REMOTE_DIST_EXTRA}"

if [[ -n "${DEPLOY_SSH_KEY:-}" && -f "${DEPLOY_SSH_KEY}" ]]; then
  exec "${SCRIPT_DIR}/sync-market-dist-key.sh"
fi

for candidate in \
  "${MARKET_DIR}/keys/id_ed25519" \
  "${MARKET_DIR}/keys/424334.pem" \
  "${HOME}/.ssh/id_ed25519" \
  "${HOME}/.ssh/424334.pem"; do
  if [[ -f "${candidate}" ]]; then
    export DEPLOY_SSH_KEY="${candidate}"
    echo "[info] 使用私钥: ${DEPLOY_SSH_KEY}"
    exec "${SCRIPT_DIR}/sync-market-dist-key.sh"
  fi
done

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "[err] 未找到私钥，也未设置 DEPLOY_SSH_PASSWORD。" >&2
  echo "  私钥: 放到 market/keys/id_ed25519 或 ~/.ssh/424334.pem" >&2
  echo "  密码: DEPLOY_SSH_PASSWORD='…' $0" >&2
  echo "  或复制 .deploy-ssh.local.example → .deploy-ssh.local" >&2
  exit 2
fi

exec "${SCRIPT_DIR}/sync-market-dist-password.sh"
