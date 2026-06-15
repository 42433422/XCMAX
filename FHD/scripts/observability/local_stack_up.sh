#!/usr/bin/env bash
# Local Docker observability for M0 evidence / dev (Prometheus :9091 + Grafana :3000).
# Scrapes host FastAPI via prometheus.local.yml (default host.docker.internal:5100).
#
#   bash FHD/scripts/observability/local_stack_up.sh
#   XCAGI_METRICS_TARGET=host.docker.internal:5000 bash FHD/scripts/observability/local_stack_up.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROM_CFG="${REPO_ROOT}/k8s/monitoring/prometheus/prometheus.local.yml"
NETWORK="${XCAGI_OBS_NETWORK:-xcagi-observability}"
PROM_CONTAINER="${XCAGI_PROM_CONTAINER:-xcagi-prom-local}"
GRAF_CONTAINER="${XCAGI_GRAF_CONTAINER:-xcagi-graf-local}"
METRICS_TARGET="${XCAGI_METRICS_TARGET:-host.docker.internal:5100}"

log() { printf '\033[36m[local-obs]\033[0m %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon not running" >&2; exit 1; }
[[ -f "${PROM_CFG}" ]] || { echo "missing ${PROM_CFG}" >&2; exit 1; }

# Render scrape target override if non-default
TMP_CFG="$(mktemp)"
sed "s|host.docker.internal:5100|${METRICS_TARGET}|g" "${PROM_CFG}" > "${TMP_CFG}"

docker network create "${NETWORK}" 2>/dev/null || true

if docker ps -a --format '{{.Names}}' | grep -qx "${PROM_CONTAINER}"; then
  docker rm -f "${PROM_CONTAINER}" >/dev/null 2>&1 || true
fi
if docker ps -a --format '{{.Names}}' | grep -qx "${GRAF_CONTAINER}"; then
  docker rm -f "${GRAF_CONTAINER}" >/dev/null 2>&1 || true
fi

log "Starting Prometheus on http://127.0.0.1:9091 (scraping ${METRICS_TARGET})"
docker run -d --name "${PROM_CONTAINER}" --network "${NETWORK}" \
  -p 127.0.0.1:9091:9090 \
  -v "${TMP_CFG}:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v2.53.0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-lifecycle

log "Starting Grafana on http://127.0.0.1:3000 (admin/admin123)"
docker run -d --name "${GRAF_CONTAINER}" --network "${NETWORK}" \
  -p 127.0.0.1:3000:3000 \
  -e GF_SECURITY_ADMIN_USER=admin \
  -e GF_SECURITY_ADMIN_PASSWORD=admin123 \
  -e GF_USERS_ALLOW_SIGN_UP=false \
  grafana/grafana:11.1.0

rm -f "${TMP_CFG}"

log "Done. Ensure FastAPI exposes /metrics on ${METRICS_TARGET}"
log "Export M0 panels: GRAFANA_URL=http://127.0.0.1:3000 bash FHD/scripts/observability/export_m0_panels.sh"
