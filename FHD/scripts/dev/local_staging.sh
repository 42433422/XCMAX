#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 本地 Mac Staging 一键启停脚本
#
# 用法:
#   bash scripts/dev/local_staging.sh up       # 启动 staging
#   bash scripts/dev/local_staging.sh down     # 停止 staging
#   bash scripts/dev/local_staging.sh logs     # 查看日志
#   bash scripts/dev/local_staging.sh health   # 健康检查
#   bash scripts/dev/local_staging.sh verify   # 验证 Neuro Bus 7 开关
#   bash scripts/dev/local_staging.sh restart  # 重启 staging
#   bash scripts/dev/local_staging.sh status   # 查看服务状态

set -euo pipefail

FHD_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$FHD_ROOT/docker-compose.staging.yml"
HEALTH_URL="http://localhost:5101/health"

cd "$FHD_ROOT"

# 检查 docker 是否可用
check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ docker 未安装,请先安装 Docker Desktop for Mac"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker daemon 未运行,请启动 Docker Desktop"
    exit 1
  fi
}

# 启动 staging
cmd_up() {
  check_docker
  echo "🚀 启动本地 Mac Staging..."
  docker compose -f "$COMPOSE_FILE" up -d --build
  echo ""
  echo "✅ Staging 已启动"
  echo "   Backend:  http://localhost:5101"
  echo "   Frontend: http://localhost:8101"
  echo "   Redis:    localhost:6380"
  echo ""
  echo "等待 backend 健康检查..."
  for i in {1..30}; do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      echo "✅ Backend 健康检查通过"
      return 0
    fi
    sleep 2
  done
  echo "⚠️  Backend 30 秒内未就绪,请检查日志: bash scripts/dev/local_staging.sh logs"
}

# 停止 staging
cmd_down() {
  check_docker
  echo "🛑 停止本地 Mac Staging..."
  docker compose -f "$COMPOSE_FILE" down
  echo "✅ Staging 已停止"
}

# 查看日志
cmd_logs() {
  check_docker
  local service="${1:-backend}"
  docker compose -f "$COMPOSE_FILE" logs -f "$service"
}

# 健康检查
cmd_health() {
  echo "🔍 健康检查..."
  if curl -sf "$HEALTH_URL"; then
    echo ""
    echo "✅ Backend 健康"
  else
    echo "❌ Backend 不健康"
    exit 1
  fi
}

# 验证 Neuro Bus 7 开关
cmd_verify() {
  echo "🔍 验证 Neuro Bus 7 开关(在容器内执行)..."
  docker compose -f "$COMPOSE_FILE" exec -T backend python -c "
import os
vars = [
    'XCAGI_NEURO_BUS_DEDUP',
    'XCAGI_NEURO_BUS_CIRCUIT',
    'XCAGI_NEURO_BUS_RATE_LIMIT',
    'XCAGI_NEURO_BUS_TRACE',
    'XCAGI_NEURO_BUS_LIFELINE',
    'XCAGI_NEURO_BUS_DLQ_AUTO',
    'XCAGI_NEURO_BUS_SLA_LOG',
]
all_ok = True
for v in vars:
    val = os.environ.get(v, '')
    ok = val == '1'
    status = '✅' if ok else '❌'
    print(f'  {status} {v}: {val}')
    if not ok:
        all_ok = False
print()
print('✅ 所有 Neuro Bus 开关已启用' if all_ok else '❌ 部分开关未启用')
exit(0 if all_ok else 1)
"
}

# 重启 staging
cmd_restart() {
  check_docker
  echo "🔄 重启本地 Mac Staging..."
  docker compose -f "$COMPOSE_FILE" restart
  echo "✅ Staging 已重启"
}

# 查看状态
cmd_status() {
  check_docker
  docker compose -f "$COMPOSE_FILE" ps
}

# 主入口
case "${1:-}" in
  up)
    cmd_up
    ;;
  down)
    cmd_down
    ;;
  logs)
    shift
    cmd_logs "$@"
    ;;
  health)
    cmd_health
    ;;
  verify)
    cmd_verify
    ;;
  restart)
    cmd_restart
    ;;
  status)
    cmd_status
    ;;
  *)
    echo "用法: bash $0 {up|down|logs|health|verify|restart|status}"
    echo ""
    echo "命令:"
    echo "  up       启动 staging(构建并后台运行)"
    echo "  down     停止 staging"
    echo "  logs     查看日志(默认 backend,可指定服务)"
    echo "  health   健康检查"
    echo "  verify   验证 Neuro Bus 7 开关"
    echo "  restart  重启 staging"
    echo "  status   查看服务状态"
    exit 1
    ;;
esac
