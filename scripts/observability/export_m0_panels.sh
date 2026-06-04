#!/usr/bin/env bash
# 导出 M0 四域 Grafana 面板 PNG → docs/evidence/slo/
# 本地: GRAFANA_URL=http://127.0.0.1:3000 --prefix local
# staging: GRAFANA_URL=https://... --prefix staging
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE_SLO="${ROOT}/docs/evidence/slo"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-admin123}"
PREFIX="local"
DATE_SUFFIX="$(date +%Y%m)"
TIME_RANGE="${TIME_RANGE:-now-15m}"
CHECK_ONLY=false

M0_PANELS=(
  "xcagi-slo:1:api-availability"
  "xcagi-mod-store:5:db-mod-sqlite-copies"
  "xcagi-slo:3:ai-chat-p95"
  "xcagi-slo:7:neurobus-delivery"
)

log() { printf '[export_m0] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
用法: bash scripts/observability/export_m0_panels.sh [--prefix local|staging] [--check-only]

  导出 M0 四域面板 PNG 至 docs/evidence/slo/。
  staging 7 天验收请将 Grafana 时间范围设为 Last 7 days 后手动 Export，或:
    TIME_RANGE=now-7d bash scripts/observability/export_m0_panels.sh --prefix staging

环境变量: GRAFANA_URL, GRAFANA_USER, GRAFANA_PASS, TIME_RANGE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    --check-only) CHECK_ONLY=true; shift ;;
    *) fail "未知参数: $1" ;;
  esac
done

[[ "${PREFIX}" == "local" || "${PREFIX}" == "staging" ]] \
  || fail "--prefix 须为 local 或 staging"

mkdir -p "${EVIDENCE_SLO}"

if ! curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then
  fail "Grafana 未就绪: ${GRAFANA_URL}（staging 需 port-forward 或内网 URL）"
fi

log "Grafana OK · prefix=${PREFIX} · range=${TIME_RANGE}"

if [[ "${CHECK_ONLY}" == true ]]; then
  log "--check-only：未导出 PNG。"
  exit 0
fi

render_panel() {
  local dash_uid="$1" panel_id="$2" out_path="$3"
  local render_url="${GRAFANA_URL}/render/d-solo/${dash_uid}?orgId=1&panelId=${panel_id}&width=1200&height=600&from=${TIME_RANGE}&to=now"
  curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${render_url}" -o "${out_path}" 2>/dev/null \
    && [[ -s "${out_path}" ]]
}

exported=0
for spec in "${M0_PANELS[@]}"; do
  IFS=':' read -r uid pid suffix <<<"${spec}"
  dest="${EVIDENCE_SLO}/grafana-${PREFIX}-m0-${suffix}-${DATE_SUFFIX}.png"
  if render_panel "${uid}" "${pid}" "${dest}"; then
    log "  ✓ ${uid}:${pid} → ${dest}"
    exported=$((exported + 1))
  else
    log "  ✗ ${uid}:${pid} 失败（可 Grafana UI → Share → Export PNG）"
  fi
done

log "已导出 ${exported}/4。7 天 staging 验收字段见 docs/evidence/slo/README.md"
