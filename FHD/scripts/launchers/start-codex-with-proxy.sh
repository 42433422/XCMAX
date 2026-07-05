#!/usr/bin/env bash
# 在 FlClash 代理已开启时，用代理环境启动 Codex（解决 API/WebSocket 不走 VPN 的问题）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_flclash-proxy-env.sh
source "${SCRIPT_DIR}/_flclash-proxy-env.sh"

CODEX_APP="/Applications/Codex.app"
CODEX_BIN="${CODEX_APP}/Contents/MacOS/Codex"

require_flclash_proxy_env

if [[ ! -d "$CODEX_APP" ]]; then
  echo "未找到 Codex.app：${CODEX_APP}" >&2
  echo "可尝试: codex app" >&2
  exit 1
fi

echo "使用代理 ${http_proxy} 启动 Codex..."
exec env \
  http_proxy="$http_proxy" https_proxy="$https_proxy" \
  HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" \
  all_proxy="$all_proxy" ALL_PROXY="$ALL_PROXY" \
  no_proxy="$no_proxy" NO_PROXY="$NO_PROXY" \
  XCMAX_CLI_PROXY="$XCMAX_CLI_PROXY" \
  "$CODEX_BIN" "$@"
