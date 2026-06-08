#!/usr/bin/env bash
# 用 SSH 私钥把本地 market/dist 推到 CVM（推荐，无需密码 expect）
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

HOST="${DEPLOY_SSH_HOST:-119.27.178.147}"
USER="${DEPLOY_SSH_USER:-root}"
PORT="${DEPLOY_SSH_PORT:-22}"
REMOTE_DIST="${DEPLOY_REMOTE_DIST:-/root/成都修茈科技有限公司/MODstore_deploy/market/dist}"
REMOTE_DIST_EXTRA="${DEPLOY_REMOTE_DIST_EXTRA:-/root/modstore-git/MODstore_deploy/market/dist}"
KEY="${DEPLOY_SSH_KEY:-}"

if [[ -z "${KEY}" ]]; then
  for candidate in \
    "${MARKET_DIR}/keys/id_ed25519" \
    "${MARKET_DIR}/keys/424334.pem" \
    "${HOME}/.ssh/id_ed25519" \
    "${HOME}/.ssh/424334.pem"; do
    if [[ -f "${candidate}" ]]; then
      KEY="${candidate}"
      break
    fi
  done
fi

if [[ -z "${KEY}" || ! -f "${KEY}" ]]; then
  echo "[err] 未找到私钥。请设置 DEPLOY_SSH_KEY 或将 id_ed25519 / 424334.pem 放到 market/keys/ 或 ~/.ssh/" >&2
  exit 2
fi

chmod 600 "${KEY}" 2>/dev/null || true

if [[ ! -f "${MARKET_DIR}/dist/index.html" ]]; then
  echo "[err] 请先构建: cd ${MARKET_DIR} && ./scripts/build-dist.sh" >&2
  exit 1
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o "Port=${PORT}" -i "${KEY}")
TARGET="${USER}@${HOST}"

echo "[info] 使用私钥 ${KEY} → ${TARGET} (port ${PORT})"
echo "[info]   ${REMOTE_DIST}"
echo "[info]   ${REMOTE_DIST_EXTRA}"
tar -C "${MARKET_DIR}/dist" -czf - . | ssh "${SSH_OPTS[@]}" "${TARGET}" \
  "set -e; cat > /tmp/market-dist-upload.tgz; for d in '${REMOTE_DIST}' '${REMOTE_DIST_EXTRA}'; do mkdir -p \"\$d\"; tar -C \"\$d\" -xzf /tmp/market-dist-upload.tgz; chmod 755 \"\$d\"; chmod -R a+rX \"\$d\"; done; rm -f /tmp/market-dist-upload.tgz; chmod o+x /root /root/成都修茈科技有限公司 /root/成都修茈科技有限公司/MODstore_deploy /root/成都修茈科技有限公司/MODstore_deploy/market 2>/dev/null || true; echo SYNC_OK"

echo "[ok] 同步完成:"
echo "     ${REMOTE_DIST}"
echo "     ${REMOTE_DIST_EXTRA}"
INDEX_JS="$(grep -oE 'assets/index-[^"]+\.js' "${MARKET_DIR}/dist/index.html" | head -1)"
echo "[ok] 本地入口: ${INDEX_JS}"
