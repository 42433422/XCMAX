#!/usr/bin/env bash
# 在 FlClash 代理已开启时，用代理环境启动 Cursor（解决 AI 请求不走 VPN 的问题）
set -euo pipefail

PROXY_HOST="127.0.0.1"
PROXY_PORT="7890"
# 优先用 /Applications 正式安装；勿从 DMG 挂载目录长期运行
if [[ -d "/Applications/Cursor.app" ]]; then
  CURSOR_APP="/Applications/Cursor.app"
elif [[ -d "/Volumes/Cursor Installer/Cursor.app" ]]; then
  echo "警告：当前从 DMG 临时目录启动，建议将 Cursor 拖入「应用程序」后重装。" >&2
  CURSOR_APP="/Volumes/Cursor Installer/Cursor.app"
else
  CURSOR_APP="/Applications/Cursor.app"
fi

if ! curl -sS --connect-timeout 2 "http://${PROXY_HOST}:${PROXY_PORT}" -o /dev/null 2>/dev/null; then
  echo "FlClash 代理 ${PROXY_HOST}:${PROXY_PORT} 未就绪，请先启动 FlClash。" >&2
  exit 1
fi

export http_proxy="http://${PROXY_HOST}:${PROXY_PORT}"
export https_proxy="http://${PROXY_HOST}:${PROXY_PORT}"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export all_proxy="socks5://${PROXY_HOST}:${PROXY_PORT}"
export ALL_PROXY="$all_proxy"
export no_proxy="localhost,127.0.0.1,*.local,10.0.0.0/8,192.168.0.0/16"
export NO_PROXY="$no_proxy"

if [[ ! -d "$CURSOR_APP" ]]; then
  echo "未找到 Cursor：$CURSOR_APP" >&2
  exit 1
fi

CURSOR_BIN="${CURSOR_APP}/Contents/MacOS/Cursor"
echo "使用代理 ${http_proxy} 启动 Cursor..."
exec env \
  http_proxy="$http_proxy" https_proxy="$https_proxy" \
  HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" \
  all_proxy="$all_proxy" ALL_PROXY="$ALL_PROXY" \
  no_proxy="$no_proxy" NO_PROXY="$NO_PROXY" \
  "$CURSOR_BIN" "$@"
