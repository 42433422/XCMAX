#!/usr/bin/env bash
# 全景仪表盘一键启动（macOS / Linux）
#
# 拉起 3 个进程：
#   1. FHD FastAPI                :5100  (FASTAPI_PORT)
#   2. MODstore FastAPI           :8788  (MODSTORE_API_PORT)
#   3. Dashboard 静态服 + 反代    :8765  (XCAGI_DASHBOARD_PORT)
#
# 用法（在仓库根 /Users/a4243342/Desktop/XCMAX 下）：
#   bash scripts/start-xcmax.sh           # 后台启动
#   bash scripts/start-xcmax.sh --fg      # 前台（阻塞、Ctrl-C 一起退）
#   bash scripts/start-xcmax.sh --stop    # 停掉所有
#   bash scripts/start-xcmax.sh --status  # 看进程/端口状态
#
# 设计要点：
#   - 端口冲突：macOS AirPlay/ControlCe 占 :5000，所以默认让 FHD 退到 :5100
#     （与 docs/xcagi-dashboard/api-base.js 的 DEFAULT_FHD_API_ORIGIN 对齐）。
#   - 端口 8765 留给 dashboard 静态服，MODstore 必须改用 :8788（与 api-base.js
#     探活地址一致）——别再用 :8765。
#   - 后台模式写 .xcmax-pids/，方便 stop/status 找到子进程；日志到 .xcmax-logs/。
#   - 如需复用已有进程，自动 skip（除非传 --force）。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FHD_DIR="$ROOT/FHD"
MODSTORE_DIR="$ROOT/成都修茈科技有限公司/MODstore_deploy"
PIDS_DIR="$ROOT/.xcmax-pids"
LOGS_DIR="$ROOT/.xcmax-logs"
mkdir -p "$PIDS_DIR" "$LOGS_DIR"

# 端口（可被同名环境变量覆盖）
FHD_PORT="${FASTAPI_PORT:-5100}"
MODSTORE_PORT="${MODSTORE_API_PORT:-8788}"
DASH_PORT="${XCAGI_DASHBOARD_PORT:-8765}"

# 工具（系统 python3 常为 3.9，FHD 需 3.10+）
if [[ -z "${PYTHON:-}" && -x "$FHD_DIR/.venv/bin/python" ]]; then
  PY="$FHD_DIR/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

# 子进程 pid 写入 / 读取
pidfile() { echo "$PIDS_DIR/$1.pid"; }
is_alive() { local p; p=$(cat "$(pidfile "$1")" 2>/dev/null || true); [[ -n "${p:-}" ]] && kill -0 "$p" 2>/dev/null; }
say()      { printf '\033[1;36m[start-xcmax]\033[0m %s\n' "$*"; }
warn()     { printf '\033[1;33m[start-xcmax]\033[0m %s\n' "$*" >&2; }
die()      { printf '\033[1;31m[start-xcmax]\033[0m %s\n' "$*" >&2; exit 1; }

port_in_use() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$p" -sTCP:LISTEN -nP 2>/dev/null | grep -q LISTEN && return 0 || return 1
  fi
  # 退化方案：nc -z
  (echo > "/dev/tcp/127.0.0.1/$p") 2>/dev/null
}

start_fhd() {
  local name=fhd
  if is_alive "$name"; then warn "[$name] 已在运行 pid=$(cat "$(pidfile "$name")")，skip"; return 0; fi
  if port_in_use "$FHD_PORT"; then die "FHD 端口 $FHD_PORT 已被占（请换 FASTAPI_PORT 或先 --stop）"; fi
  say "启动 FHD FastAPI on :$FHD_PORT …"
  (
    cd "$FHD_DIR"
    FASTAPI_PORT="$FHD_PORT" nohup "$PY" run.py >"$LOGS_DIR/fhd.log" 2>&1 &
    echo $! >"$PIDS_DIR/$name.pid"
  )
}

start_modstore() {
  local name=modstore
  if is_alive "$name"; then warn "[$name] 已在运行 pid=$(cat "$(pidfile "$name")")，skip"; return 0; fi
  if port_in_use "$MODSTORE_PORT"; then die "MODstore 端口 $MODSTORE_PORT 已被占（请换 MODSTORE_API_PORT 或先 --stop）"; fi
  say "启动 MODstore FastAPI on :$MODSTORE_PORT …"
  (
    cd "$MODSTORE_DIR"
    MODSTORE_API_PORT="$MODSTORE_PORT" nohup "$PY" -m modstore_server >"$LOGS_DIR/modstore.log" 2>&1 &
    echo $! >"$PIDS_DIR/$name.pid"
  )
}

start_dashboard() {
  local name=dashboard
  if is_alive "$name"; then warn "[$name] 已在运行 pid=$(cat "$(pidfile "$name")")，skip"; return 0; fi
  if port_in_use "$DASH_PORT"; then die "Dashboard 端口 $DASH_PORT 已被占（请换 XCAGI_DASHBOARD_PORT 或先 --stop）"; fi
  say "启动 Dashboard 静态服 on :$DASH_PORT …"
  (
    cd "$ROOT"
    XCAGI_DASHBOARD_PORT="$DASH_PORT" \
    XCAGI_API_BACKEND="http://127.0.0.1:$FHD_PORT" \
      nohup bash scripts/serve_xcagi_dashboard.sh >"$LOGS_DIR/dashboard.log" 2>&1 &
    echo $! >"$PIDS_DIR/$name.pid"
  )
}

wait_port() {
  local port="$1" name="$2" tries=30
  while (( tries-- > 0 )); do
    if port_in_use "$port"; then say "[$name] :$port 就绪"; return 0; fi
    sleep 0.5
  done
  warn "[$name] :$port 30 次重试仍未就绪，请看 $LOGS_DIR/$name.log"
  return 1
}

do_start() {
  start_fhd
  start_modstore
  start_dashboard
  wait_port "$FHD_PORT"      fhd
  wait_port "$MODSTORE_PORT" modstore
  wait_port "$DASH_PORT"     dashboard
  cat <<EOF

$(say '全部就绪 → 打开:')
  http://127.0.0.1:$DASH_PORT/XCAGI-Full-Pipeline.html
  http://127.0.0.1:$DASH_PORT/XCAGI-Five-Line.html

$(say '健康检查:')
  curl -sS http://127.0.0.1:$FHD_PORT/api/xcmax/health
  curl -sS http://127.0.0.1:$MODSTORE_PORT/api/health

$(say '日志:')    tail -F $LOGS_DIR/*.log
$(say '停止:')    bash scripts/start-xcmax.sh --stop
EOF
}

do_stop() {
  for n in fhd modstore dashboard; do
    local pf; pf="$(pidfile "$n")"
    if [[ -f "$pf" ]]; then
      local p; p=$(cat "$pf")
      if kill -0 "$p" 2>/dev/null; then
        say "停止 $n (pid=$p)…"
        kill "$p" 2>/dev/null || true
        sleep 0.3
        kill -9 "$p" 2>/dev/null || true
      fi
      rm -f "$pf"
    fi
  done
}

do_status() {
  for n in fhd modstore dashboard; do
    if is_alive "$n"; then
      say "[$n] 运行中 pid=$(cat "$(pidfile "$n")")"
    else
      warn "[$n] 未运行"
    fi
  done
  for entry in "FHD $FHD_PORT" "MODstore $MODSTORE_PORT" "Dashboard $DASH_PORT"; do
    set -- $entry; n=$1; p=$2
    if port_in_use "$p"; then say "端口 :$p ($n) 已被占用（不一定是本脚本拉起的）"
    else warn "端口 :$p ($n) 空闲"; fi
  done
}

case "${1:-start}" in
  --fg|fg)
    trap 'do_stop; exit 0' INT TERM
    do_start
    wait
    ;;
  --stop|stop)   do_stop ;;
  --status|st)   do_status ;;
  --help|-h)
    sed -n '2,18p' "$0"
    ;;
  *)             do_start ;;
esac
