#!/usr/bin/env bash
# 本地 Prometheus + Grafana 一键启动（T36–T37 本地可复现部分）
# 成功时：尝试导出 M0 四域面板 PNG → docs/evidence/slo/ 与 docs/observability/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${ROOT}/scripts/observability/docker-compose.local.yml"
OBS_DIR="${ROOT}/docs/observability"
EVIDENCE_SLO="${ROOT}/docs/evidence/slo"
LEGACY_SHOT="${OBS_DIR}/grafana-local-202606.png"
API_URL="${BASE_URL:-http://127.0.0.1:5000}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-admin123}"

# M0 路径图四域：API / DB / AI / NeuroBus（dashboard_uid:panel_id:文件名后缀）
M0_PANELS=(
  "xcagi-slo:1:api-availability"
  "xcagi-mod-store:5:db-mod-sqlite-copies"
  "xcagi-slo:3:ai-chat-p95"
  "xcagi-slo:7:neurobus-delivery"
)

log() { printf '[local_stack] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
用法: bash scripts/observability/local_stack_up.sh [--check-only]

  --check-only  仅校验 compose/配置路径（无需 Docker）

环境变量: BASE_URL, GRAFANA_URL, GRAFANA_USER, GRAFANA_PASS
EOF
}

check_paths() {
  [[ -f "${COMPOSE_FILE}" ]] || fail "缺少 compose: ${COMPOSE_FILE}"
  [[ -f "${ROOT}/k8s/monitoring/prometheus/prometheus.local.yml" ]] \
    || fail "缺少 prometheus.local.yml"
  [[ -d "${ROOT}/k8s/monitoring/grafana/dashboards" ]] \
    || fail "缺少 dashboards 目录"
  log "路径校验通过（ROOT=${ROOT}）"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

check_paths

if [[ "${1:-}" == "--check-only" ]]; then
  log "--check-only：未启动容器。安装 Docker 后去掉该参数即可起栈。"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  fail "未检测到 docker。请安装 Docker Desktop 或 Colima；或先运行: $0 --check-only"
fi

COMPOSE=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

mkdir -p "${OBS_DIR}" "${EVIDENCE_SLO}"

log "启动 Prometheus + Grafana（compose: ${COMPOSE_FILE}）"
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" up -d

log "等待 Grafana 就绪…"
for _ in $(seq 1 30); do
  if curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1 || fail "Grafana 未在 ${GRAFANA_URL} 就绪"

log "生成 API 探针流量（可选，需本地 FastAPI 在 ${API_URL}）"
if curl -sf "${API_URL}/api/health" >/dev/null 2>&1; then
  for _ in $(seq 1 20); do
    curl -sf "${API_URL}/api/health" >/dev/null || true
    curl -sf "${API_URL}/metrics" >/dev/null || true
  done
  log "已对 ${API_URL} 发送探针请求（Prometheus 经 host.docker.internal:5000 抓取）"
else
  log "跳过 API 流量：${API_URL}/api/health 不可达（可另开终端 make dev 后重跑本脚本）"
fi

render_panel() {
  local dash_uid="$1" panel_id="$2" out_path="$3"
  local render_url="${GRAFANA_URL}/render/d-solo/${dash_uid}?orgId=1&panelId=${panel_id}&width=1200&height=600&from=now-15m&to=now"
  curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${render_url}" -o "${out_path}" 2>/dev/null \
    && [[ -s "${out_path}" ]]
}

log "尝试导出 M0 四域面板 PNG → ${EVIDENCE_SLO}/"
exported=0
for spec in "${M0_PANELS[@]}"; do
  IFS=':' read -r uid pid suffix <<<"${spec}"
  dest="${EVIDENCE_SLO}/grafana-local-m0-${suffix}-202606.png"
  if render_panel "${uid}" "${pid}" "${dest}"; then
    log "  ✓ ${uid} panel ${pid} → ${dest}"
    exported=$((exported + 1))
    if [[ "${suffix}" == "api-availability" ]]; then
      cp -f "${dest}" "${LEGACY_SHOT}" 2>/dev/null || true
    fi
  else
    log "  ✗ ${uid} panel ${pid} 自动截图失败（可手动 Export PNG）"
  fi
done

if [[ "${exported}" -eq 0 ]]; then
  log "自动截图均未成功。请手动："
  log "  1) 打开 ${GRAFANA_URL}（${GRAFANA_USER}/${GRAFANA_PASS}）"
  log "  2) Dashboards → XCAGI 文件夹 → 按 docs/evidence/README.md M0 表导出"
  log "  3) 保存至 ${EVIDENCE_SLO}/ 与 ${LEGACY_SHOT}"
else
  log "已导出 ${exported}/4 张 M0 面板（无指标时 PNG 可能为空图，属预期）"
fi

log "本地栈就绪：Prometheus http://localhost:9090 · Grafana ${GRAFANA_URL}"
log "停止：${COMPOSE[*]} -f ${COMPOSE_FILE} down"
