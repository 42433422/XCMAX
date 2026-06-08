#!/usr/bin/env bash
# 组件化发布：仅 market 前端（MODstore_deploy/market）。
# - 不触碰 Python venv 或 Java mvn；那两项由 python-release.sh / java-release.sh 独立发布。
# - 用于替代 remote_sync_extract.sh 中的 `cd market && npm install && npm run build` 段。
#
# 环境变量：
#   MODSTORE_MARKET_DIR     market 工作目录。默认使用脚本父目录 + /market。
#   VITE_PUBLIC_BASE        默认 "/market/"；根站点部署改为 "/"。
#   MODSTORE_NPM_INSTALL_FLAGS  默认 "--no-audit --legacy-peer-deps"（与生产机一致）。

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
export DEPLOY_SCRIPT_ID="node_release_sh"
if [ -f "${SCRIPT_DIR}/lib/deploy_emit.sh" ]; then
  # shellcheck source=lib/deploy_emit.sh
  . "${SCRIPT_DIR}/lib/deploy_emit.sh"
else
  deploy_emit() { :; }
  deploy_emit_summary_json() { :; }
fi
DEFAULT_MARKET_DIR="$(cd -- "$SCRIPT_DIR/../market" &>/dev/null && pwd 2>/dev/null || true)"
MARKET_DIR="${MODSTORE_MARKET_DIR:-$DEFAULT_MARKET_DIR}"
PUBLIC_BASE="${VITE_PUBLIC_BASE:-/market/}"
NPM_FLAGS="${MODSTORE_NPM_INSTALL_FLAGS:---no-audit --legacy-peer-deps}"

echo "[info] node-release.sh market_dir=${MARKET_DIR} base=${PUBLIC_BASE}"
deploy_emit bootstrap started "node_release"
if [ -z "${MARKET_DIR}" ] || [ ! -f "${MARKET_DIR}/package.json" ]; then
  echo "[err] ${MARKET_DIR} 下未发现 package.json，无法执行 market 发布" >&2
  deploy_emit bootstrap failed "missing_package_json exit=1"
  exit 1
fi
deploy_emit bootstrap ok
cd "${MARKET_DIR}"

if ! command -v npm >/dev/null 2>&1; then
  echo "[err] npm not found on remote" >&2
  deploy_emit npm_toolchain failed "npm_missing exit=1"
  exit 1
fi

deploy_emit npm_install started
# 生产机上 package-lock 偶发与 workspace 不同步，沿用既定做法用 install（非 ci）并带 legacy-peer-deps
echo "[ok] npm install ${NPM_FLAGS}"
# shellcheck disable=SC2086
npm install ${NPM_FLAGS}
deploy_emit npm_install ok

deploy_emit vite_bundle_build started
export VITE_PUBLIC_BASE="${PUBLIC_BASE}"
echo "[ok] npm run build (VITE_PUBLIC_BASE=${PUBLIC_BASE})"
npm run build
deploy_emit vite_bundle_build ok

deploy_emit verify_dist started
if [ ! -d dist ]; then
  echo "[err] build 完成但未生成 dist/；检查 vite 配置与错误日志" >&2
  deploy_emit verify_dist failed "no_dist_directory exit=1"
  deploy_emit_summary_json true false false false || true
  exit 1
fi
deploy_emit verify_dist ok
deploy_emit_summary_json true true false false || true
echo "[ok] node-release done; dist at $(pwd)/dist"
