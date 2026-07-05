#!/usr/bin/env bash
# 探测 FlClash / Clash 本地代理并导出标准 proxy 环境变量。
# 用法: source "$(dirname "$0")/_flclash-proxy-env.sh"  或  eval "$(... export_proxy_env)"
set -euo pipefail

FLCLASH_PROXY_HOST="${FLCLASH_PROXY_HOST:-127.0.0.1}"
FLCLASH_PROXY_PORT="${FLCLASH_PROXY_PORT:-7890}"

_proxy_port_open() {
  local host="$1" port="$2"
  python3 - "$host" "$port" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket()
s.settimeout(1.5)
try:
    s.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
}

resolve_flclash_proxy_url() {
  local port="${FLCLASH_PROXY_PORT}"
  if _proxy_port_open "${FLCLASH_PROXY_HOST}" "${port}"; then
    echo "http://${FLCLASH_PROXY_HOST}:${port}"
    return 0
  fi
  for port in 7897 7891 1087 1080; do
    if _proxy_port_open "${FLCLASH_PROXY_HOST}" "${port}"; then
      echo "http://${FLCLASH_PROXY_HOST}:${port}"
      return 0
    fi
  done
  return 1
}

export_flclash_proxy_env() {
  local proxy_url
  proxy_url="$(resolve_flclash_proxy_url)" || return 1
  export http_proxy="${proxy_url}"
  export https_proxy="${proxy_url}"
  export HTTP_PROXY="${proxy_url}"
  export HTTPS_PROXY="${proxy_url}"
  export all_proxy="socks5://${FLCLASH_PROXY_HOST}:${FLCLASH_PROXY_PORT}"
  export ALL_PROXY="${all_proxy}"
  export no_proxy="localhost,127.0.0.1,*.local,10.0.0.0/8,192.168.0.0/16"
  export NO_PROXY="${no_proxy}"
  export XCMAX_CLI_PROXY="${proxy_url}"
}

require_flclash_proxy_env() {
  if export_flclash_proxy_env; then
    return 0
  fi
  echo "FlClash 代理 ${FLCLASH_PROXY_HOST}:${FLCLASH_PROXY_PORT} 未就绪，请先启动 FlClash。" >&2
  return 1
}
