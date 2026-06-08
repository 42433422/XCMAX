#!/usr/bin/env bash
# 生产全量：market/dist + modstore_server（凭 .deploy-ssh.local）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${MARKET_DIR}"

export DEPLOY_ALLOW_PUBLIC=1

echo "=== 1/2 构建并同步前端 dist ==="
if [[ ! -f dist/index.html ]]; then
  bash scripts/build-dist.sh
else
  bash scripts/build-dist.sh
fi
bash scripts/ssh-push-update.sh

echo ""
echo "=== 2/2 同步 modstore_server 并重启 API ==="
bash scripts/ssh-push-backend.sh

echo ""
echo "[done] 前后端已部署到 ${DEPLOY_SSH_HOST:-119.27.178.147}"
