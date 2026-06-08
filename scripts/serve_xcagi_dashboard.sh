#!/usr/bin/env bash
# 全景仪表盘本地开发服：静态 + /api /metrics /prometheus /grafana 反代
#
# 用法（XCMAX 根目录）:
#   bash scripts/serve_xcagi_dashboard.sh
#
# 终端 2：FastAPI :5000 · 终端 3（可选）：bash FHD/scripts/observability/local_stack_up.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${XCAGI_DASHBOARD_PORT:-8765}"
API_BACKEND="${XCAGI_API_BACKEND:-http://127.0.0.1:5000}"
PROMETHEUS_BACKEND="${XCAGI_PROMETHEUS_BACKEND:-http://127.0.0.1:9091}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --api-backend) API_BACKEND="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

exec python3 "$ROOT/FHD/scripts/serve_static_cached.py" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --directory "$ROOT" \
  --api-backend "$API_BACKEND" \
  --prometheus-backend "$PROMETHEUS_BACKEND" \
  --grafana-backend "${XCAGI_GRAFANA_BACKEND:-http://127.0.0.1:3000}" \
  --grafana-user "${GRAFANA_USER:-admin}" \
  --grafana-pass "${GRAFANA_PASS:-admin123}"
