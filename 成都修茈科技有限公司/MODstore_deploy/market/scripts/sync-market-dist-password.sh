#!/usr/bin/env bash
# 用 root 密码把本地 market/dist 推到 CVM（不需要 id_ed25519 / 424334.pem）
# 可选: DEPLOY_SSH_PORT（默认 22），见 .deploy-ssh.local.example
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

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "[err] 未设置 DEPLOY_SSH_PASSWORD。" >&2
  echo "  1) 复制 ${MARKET_DIR}/.deploy-ssh.local.example → .deploy-ssh.local 并填写密码" >&2
  echo "  2) 或: DEPLOY_SSH_PASSWORD='你的root密码' $0" >&2
  exit 2
fi

if [[ ! -f "${MARKET_DIR}/dist/index.html" ]]; then
  echo "[err] 请先构建: cd ${MARKET_DIR} && npm run build" >&2
  exit 1
fi

exec /usr/bin/expect -f "${SCRIPT_DIR}/sync-market-dist-password.expect"
