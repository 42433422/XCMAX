#!/usr/bin/env bash
# 构建 market/dist（无全局 npm 时用 Cursor 自带 node 调 vite）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${MARKET_DIR}"

NODE="${NODE:-}"
if [[ -z "${NODE}" ]]; then
  for candidate in \
    "$(command -v node 2>/dev/null || true)" \
    "/opt/homebrew/bin/node" \
    "/usr/local/bin/node" \
    "/Volumes/Cursor Installer/Cursor.app/Contents/Resources/app/resources/helpers/node"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      NODE="${candidate}"
      break
    fi
  done
fi
if [[ -z "${NODE}" || ! -x "${NODE}" ]]; then
  echo "[err] 未找到 node。请安装 Node 20+ 或设置 NODE=/path/to/node" >&2
  exit 1
fi

echo "[build] node=$("$NODE" --version) vite build …"
"$NODE" node_modules/vite/bin/vite.js build
echo "[ok] dist 已更新: ${MARKET_DIR}/dist"
