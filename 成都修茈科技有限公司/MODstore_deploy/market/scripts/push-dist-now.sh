#!/usr/bin/env bash
# 在本机终端执行（需能 SSH 到 CVM）。密码通过环境变量传入，勿提交 Git。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${MARKET_DIR}"

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "用法: DEPLOY_SSH_PASSWORD='你的root密码' ./scripts/push-dist-now.sh" >&2
  echo "可选: DEPLOY_SSH_PORT=22" >&2
  exit 2
fi

if [[ ! -f dist/index.html ]]; then
  echo "[build] dist 缺失，正在构建…"
  ./scripts/build-dist.sh
fi

echo "[info] 已切换为内网/机内部署入口（不走公网 SSH）" >&2
exec ./scripts/deploy-internal.sh

echo ""
echo "验证线上入口（期望新 index-*.js，含「试跑并自动生成」）："
curl -sk 'https://119.27.178.147/market/' | grep -oE 'index-[a-zA-Z0-9_-]+\.js|market-build:[^<]+' | head -3
