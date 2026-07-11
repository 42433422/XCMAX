#!/usr/bin/env bash
# 启动桌面云中继轮询（手机超级员工 -> 本机 Cursor CLI）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "缺少 ${PY}，请先在 FHD 目录创建 venv" >&2
  exit 1
fi
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
# 避免 shell 代理干扰 httpx TLS
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy
exec "$PY" -c "
import sys, time
sys.path.insert(0, '${ROOT}')
from app.services.mobile_relay_desktop_client import start_desktop_relay_poller
ok = start_desktop_relay_poller()
print('desktop relay poller started:', ok, flush=True)
while True:
    time.sleep(3600)
"
