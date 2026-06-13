#!/usr/bin/env bash
# Export Grafana M0 SLO panel PNGs for evidence/slo.
# Usage:
#   TIME_RANGE=now-7d GRAFANA_URL=http://127.0.0.1:30300 \
#     bash scripts/observability/export_m0_panels.sh --prefix staging
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE_DIR="${ROOT}/docs/evidence/slo"
PREFIX="local"
GRAF_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
GRAF_USER="${GRAFANA_USER:-admin}"
GRAF_PASS="${GRAFANA_PASS:-admin123}"
TIME_RANGE="${TIME_RANGE:-now-15m}"
WIDTH="${GRAFANA_RENDER_WIDTH:-1200}"
HEIGHT="${GRAFANA_RENDER_HEIGHT:-600}"

log() { printf '[export-m0] %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --time-range) TIME_RANGE="$2"; shift 2 ;;
    *) log "Unknown arg: $1"; exit 1 ;;
  esac
done

TODAY="$(date +%Y%m%d)"
mkdir -p "${EVIDENCE_DIR}"

# Panel ids align with k8s/monitoring/grafana/dashboards/xcagi-slo.json
PANELS=(
  "api_availability:1"
  "api_latency_p95:2"
  "ai_chat_first_byte_p95_ms:3"
  "api_error_rate:5"
  "api_login_p95_ms:6"
  "neurobus_delivery:7"
)

for entry in "${PANELS[@]}"; do
  key="${entry%%:*}"
  panel_id="${entry##*:}"
  out="${EVIDENCE_DIR}/grafana-${PREFIX}-m0-${key}-${TODAY}.png"
  url="${GRAF_URL}/render/d-solo/xcagi-slo?from=${TIME_RANGE}&to=now&panelId=${panel_id}&width=${WIDTH}&height=${HEIGHT}"
  if curl -sf -u "${GRAF_USER}:${GRAF_PASS}" -o "${out}" "${url}"; then
    log "OK ${out}"
  else
    log "WARN failed ${out} (Grafana unreachable or auth wrong)"
  fi
done

log "Done → ${EVIDENCE_DIR}/grafana-${PREFIX}-m0-*-${TODAY}.png"
