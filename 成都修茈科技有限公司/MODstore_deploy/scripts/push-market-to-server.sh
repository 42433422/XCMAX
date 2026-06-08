#!/usr/bin/env bash
# 将市场前端同步到线上：在服务器上 git pull + npm ci + build（产物即 Nginx 指向的 dist）。
#
# 环境变量（可选）：
#   DEPLOY_SSH          SSH 目标，默认 root@119.27.178.147
#   DEPLOY_REMOTE_REPO  服务器上仓库根目录，默认 /root/成都修茈科技有限公司
#   DEPLOY_GIT_BRANCH   拉取分支，默认 main
#   GIT_PUSH=1          先在本仓库执行 git push origin <分支>（需已 commit）
#
# 用法：
#   chmod +x scripts/push-market-to-server.sh
#   ./scripts/push-market-to-server.sh
#   GIT_PUSH=1 ./scripts/push-market-to-server.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODSTORE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODSTORE_ROOT}/.." && pwd)"

DEPLOY_SSH="${DEPLOY_SSH:-root@119.27.178.147}"
DEPLOY_REMOTE_REPO="${DEPLOY_REMOTE_REPO:-/root/成都修茈科技有限公司}"
DEPLOY_GIT_BRANCH="${DEPLOY_GIT_BRANCH:-main}"

if [[ "${GIT_PUSH:-}" == "1" ]]; then
  echo "[push-market] GIT_PUSH=1：正在 push origin ${DEPLOY_GIT_BRANCH} …"
  (cd "${REPO_ROOT}" && git push "origin" "${DEPLOY_GIT_BRANCH}")
fi

echo "[push-market] SSH ${DEPLOY_SSH} → ${DEPLOY_REMOTE_REPO}（分支 ${DEPLOY_GIT_BRANCH}）"

ssh -o BatchMode=yes "${DEPLOY_SSH}" bash -s -- "${DEPLOY_REMOTE_REPO}" "${DEPLOY_GIT_BRANCH}" <<'REMOTE'
set -euo pipefail
cd "$1"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "[错误] 不是 git 仓库: $1" >&2
  exit 1
fi
git fetch origin "$2"
# 清掉 market 下未纳入版本管理的内容，避免与即将检出的文件冲突
git clean -fd -- "MODstore_deploy/market" 2>/dev/null || true
# 与 origin 一致，避免线上曾手动改文件导致与远程不一致
git reset --hard "origin/$2"
cd MODstore_deploy/market
export VITE_PUBLIC_BASE=/market/
rm -rf node_modules
# 与 npm ci 不同：在 Linux 上只装本机需要的一套可选依赖，避免 lock 里多平台 @esbuild/* 触发 EBADPLATFORM
npm install
npm run build
echo "[ok] dist 已更新: $(pwd)/dist"
REMOTE
