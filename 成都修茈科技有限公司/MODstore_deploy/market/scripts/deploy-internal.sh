#!/usr/bin/env bash
# 不走公网推送：优先 VPC 内网 SSH；否则在 CVM 本机（OrcaTerm）构建/打补丁
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

HOST="${DEPLOY_SSH_HOST:-}"

is_private_host() {
  local h="${1%%:*}"
  [[ "$h" =~ ^10\. ]] && return 0
  [[ "$h" =~ ^192\.168\. ]] && return 0
  [[ "$h" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]] && return 0
  [[ "$h" == "localhost" || "$h" == "127.0.0.1" ]] && return 0
  return 1
}

echo "=== market 内网/机内部署（不走公网 119.27.178.147:22）==="
echo ""

if [[ -n "${HOST}" ]] && is_private_host "${HOST}"; then
  echo "[route] 内网 SSH → ${DEPLOY_SSH_USER:-root}@${HOST}:${DEPLOY_SSH_PORT:-22}"
  exec "${SCRIPT_DIR}/ssh-push-update.sh"
fi

if [[ -n "${HOST}" ]] && ! is_private_host "${HOST}"; then
  echo "[skip] DEPLOY_SSH_HOST=${HOST} 为公网地址，本脚本不通过公网推送。"
  echo "       若确需公网 SSH，请用: DEPLOY_ALLOW_PUBLIC=1 ./scripts/ssh-push-update.sh"
  echo ""
fi

echo "[route] 在 CVM 本机完成（腾讯云 OrcaTerm / VNC，走控制台通道，不经本机公网 SSH）"
echo ""
echo "任选其一："
echo ""
echo "── A) 服务器 git pull + build（代码需已 push 到远端仓库）──"
echo "  打开 OrcaTerm，粘贴执行:"
echo "    cd /root/成都修茈科技有限公司/MODstore_deploy/market && bash scripts/orcaterm-deploy-commands.sh"
echo "  或:"
echo "    MODSTORE_ROOT=/root/modstore-git/MODstore_deploy bash /root/成都修茈科技有限公司/MODstore_deploy/market/scripts/orcaterm-deploy-commands.sh"
echo ""
echo "── B) 最小补丁（无需 git，本机生成粘贴块）──"
echo "  在本机 Mac 执行:"
echo "    cd \"${MARKET_DIR}\""
echo "    bash scripts/orcaterm-patch-deploy.sh --regen-b64   # dist 有更新时"
echo "    bash scripts/orcaterm-patch-deploy.sh --print-remote | pbcopy"
echo "  将剪贴板整段粘贴到 OrcaTerm 执行（解压到两个 dist，本机 curl 127.0.0.1 验证）"
echo ""
echo "── C) 配置 VPC 内网后再 SSH（同一地域内网 IP）──"
echo "  复制 .deploy-ssh.local.example → .deploy-ssh.local"
echo "  设置 DEPLOY_SSH_HOST=10.x.x.x   # 腾讯云「私有网络 IP」"
echo "  再执行: ./scripts/deploy-internal.sh"
echo ""

if [[ -f "${SCRIPT_DIR}/market-patch-min.tgz.b64" ]]; then
  echo "[ok] 补丁包已存在: scripts/market-patch-min.tgz.b64"
else
  echo "[hint] 可先运行: bash scripts/orcaterm-patch-deploy.sh --regen-b64"
fi

exit 0
