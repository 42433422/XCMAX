#!/usr/bin/env bash
# 开发本机环回直连：避免 http_proxy=127.0.0.1:7890（Clash）把 localhost 拐走导致 502。
# 用法: source "$(dirname "$0")/ensure_dev_proxy_bypass.sh"
# 或:   eval "$(bash .../ensure_dev_proxy_bypass.sh --print)"
#
# 说明：
# - 本脚本只影响当前 shell / 其子进程（curl、Vite、Python）。
# - Cursor / Chrome 走「系统代理」时，仍须在 Clash Bypass 或 macOS
#   「忽略这些主机与域的代理设置」中加入 localhost,127.0.0.1,::1。
# - 启动 Cursor 请用 scripts/launchers/start-cursor-with-proxy.sh（带 Chromium bypass）。

_XCMAX_DEV_NO_PROXY_DEFAULT='localhost,127.0.0.1,::1,*.local,0.0.0.0,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'

_xcmax_merge_no_proxy() {
  local existing="${NO_PROXY:-${no_proxy:-}}"
  local merged="$_XCMAX_DEV_NO_PROXY_DEFAULT"
  if [[ -n "$existing" ]]; then
    merged="${existing},${_XCMAX_DEV_NO_PROXY_DEFAULT}"
  fi
  # 去重保序
  printf '%s' "$merged" | tr ',' '\n' | awk 'NF && !seen[$0]++' | paste -sd, -
}

ensure_dev_proxy_bypass() {
  local merged
  merged="$(_xcmax_merge_no_proxy)"
  export no_proxy="$merged"
  export NO_PROXY="$merged"
  # 给 curl 显式绕过（部分环境只认 --noproxy）
  export CURL_NOPROXY="${CURL_NOPROXY:-$merged}"
}

if [[ "${1:-}" == "--print" ]]; then
  ensure_dev_proxy_bypass
  cat <<EOF
export no_proxy=$(printf '%q' "$no_proxy")
export NO_PROXY=$(printf '%q' "$NO_PROXY")
export CURL_NOPROXY=$(printf '%q' "$CURL_NOPROXY")
EOF
  exit 0
fi

# 被 source 时直接生效
ensure_dev_proxy_bypass
