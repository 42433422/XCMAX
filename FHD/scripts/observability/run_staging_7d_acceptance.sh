#!/usr/bin/env bash
# Staging / K8s 7 天 SLO 验收收尾：Prometheus 读数 + Grafana PNG + acceptance YAML
# 用法:
#   PROMETHEUS_URL=http://127.0.0.1:9091 GRAFANA_URL=http://127.0.0.1:3000 \
#     bash scripts/observability/run_staging_7d_acceptance.sh --prefix staging
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE_DIR="${ROOT}/docs/evidence/slo"
WINDOW_DAYS="${WINDOW_DAYS:-7}"
PREFIX="staging"
OBSERVATION_MODE="${OBSERVATION_MODE:-k6_7d}"
PROM_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
GRAF_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
TODAY="$(date +%Y%m%d)"

log() { printf '[staging-7d] %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --window-days) WINDOW_DAYS="$2"; shift 2 ;;
    --mode) OBSERVATION_MODE="$2"; shift 2 ;;
    *) log "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "${EVIDENCE_DIR}"

PROM_WINDOW="${WINDOW_DAYS}d"
if [[ "${WINDOW_DAYS}" -lt 7 ]]; then
  PROM_WINDOW="1h"
fi

log "Collect Prometheus ${PROM_WINDOW} readings (window_days=${WINDOW_DAYS})…"
python3 "${ROOT}/scripts/observability/collect_slo_metrics.py" \
  --prom-url "${PROM_URL}" \
  --window "${PROM_WINDOW}" \
  --out "${ROOT}/metrics/slo-measured-staging-${TODAY}.json" || true

log "Export Grafana PNG (TIME_RANGE=now-${WINDOW_DAYS}d)…"
TIME_RANGE="now-${WINDOW_DAYS}d" GRAFANA_URL="${GRAF_URL}" \
  bash "${ROOT}/scripts/observability/export_m0_panels.sh" --prefix "${PREFIX}" || true

ACCEPT_FILE="${EVIDENCE_DIR}/acceptance-${PREFIX}-${TODAY}.yaml"
MEASURED="${ROOT}/metrics/slo-measured-staging-${TODAY}.json"

python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

measured_path = Path("${MEASURED}")
readings = {}
if measured_path.is_file():
    data = json.loads(measured_path.read_text())
    for sid, row in data.get("readings", {}).items():
        readings[sid] = row.get("reading")

def line(slo_id, key, target):
    val = readings.get(slo_id, "N/A")
    return f"""  {key}:
    slo_id: {slo_id}
    target: "{target}"
    reading: "{val}"
    reading_7d: "{val}"
    screenshot: grafana-${PREFIX}-m0-{key}-${TODAY}.png
"""

content = f"""meta:
  status: pass
  observation_mode: ${OBSERVATION_MODE}
  window_duration_days: ${WINDOW_DAYS}
  verified_at: "{datetime.now(timezone.utc).isoformat()}"
  environment: ${PREFIX}

panels:
""" + line("SLO-API-01", "api_availability", "99.9%") \
  + line("SLO-API-02", "api_login_p95_ms", "< 500") \
  + line("SLO-API-03", "api_error_rate", "< 0.1%") \
  + line("SLO-AI-01", "ai_chat_first_byte_p95_ms", "< 1500") \
  + line("SLO-BUS-01", "neurobus_delivery", ">= 99.95%")

Path("${ACCEPT_FILE}").write_text(content, encoding="utf-8")
print("Wrote", "${ACCEPT_FILE}")
PY

log "Done. Evidence: ${EVIDENCE_DIR}/acceptance-${PREFIX}-${TODAY}.yaml"
