#!/usr/bin/env bash
# Staging SLO 前置检查占位（T36–T37 解除阻塞前可跑 --check-only）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NS="${NS:-xcagi-staging}"
BASE_URL="${BASE_URL:-}"
GRAFANA_URL="${GRAFANA_URL:-}"

log() { printf '[staging_preflight] %s\n' "$*"; }
warn() { log "WARN: $*"; }
fail() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
用法: bash scripts/observability/staging_preflight.sh [--check-only]

  核对 staging 监控栈与 API 可达性；不生成假指标或 PNG。

环境变量:
  KUBECONFIG   staging 集群 kubeconfig
  NS           命名空间（默认 xcagi-staging）
  BASE_URL     staging API（例 https://api.staging.example）
  GRAFANA_URL  Grafana 基址（port-forward 或内网）
EOF
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

CHECK_ONLY="${1:-}"
[[ "${CHECK_ONLY}" == "--check-only" ]] || CHECK_ONLY=""

log "=== Staging SLO 前置检查（T36–T37）==="

# 1. 仓内路径
[[ -f "${ROOT}/k8s/monitoring/STAGING_RUNBOOK.md" ]] || fail "缺少 STAGING_RUNBOOK.md"
[[ -f "${ROOT}/docs/evidence/slo/README.md" ]] || fail "缺少 docs/evidence/slo/README.md"
[[ -f "${ROOT}/docs/evidence/slo/acceptance-TEMPLATE.yaml" ]] || fail "缺少 acceptance-TEMPLATE.yaml"
log "✓ 文档路径 OK"

# 2. promtool（可选）
if command -v promtool >/dev/null 2>&1; then
  promtool check rules "${ROOT}/k8s/monitoring/prometheus/alert_rules.yml" \
    && log "✓ alert_rules.yml 语法 OK" \
    || warn "alert_rules.yml promtool 检查失败"
else
  warn "未安装 promtool，跳过 rules 校验"
fi

# 3. kubectl（可选）
if command -v kubectl >/dev/null 2>&1 && [[ -n "${KUBECONFIG:-}" ]]; then
  if kubectl -n "${NS}" get pods -l app=prometheus >/dev/null 2>&1; then
    kubectl -n "${NS}" get pods -l 'app in (prometheus,grafana)' 2>/dev/null \
      | tail -n +2 | while read -r line; do log "  pod: ${line}"; done
    log "✓ kubectl 可访问 ${NS}"
  else
    warn "kubectl 无法列出 ${NS} Prometheus（集群未就绪或未部署）"
  fi
else
  warn "跳过 kubectl（无 KUBECONFIG 或未安装 kubectl）"
fi

# 4. API
if [[ -n "${BASE_URL}" ]]; then
  curl -sf "${BASE_URL}/api/health" >/dev/null \
    && log "✓ ${BASE_URL}/api/health 可达" \
    || warn "${BASE_URL}/api/health 不可达"
else
  warn "未设 BASE_URL，跳过 API 探针"
fi

# 5. Grafana
if [[ -n "${GRAFANA_URL}" ]]; then
  curl -sf "${GRAFANA_URL}/api/health" >/dev/null \
    && log "✓ Grafana ${GRAFANA_URL} 可达" \
    || warn "Grafana ${GRAFANA_URL} 不可达"
else
  warn "未设 GRAFANA_URL，跳过 Grafana 探针"
fi

log "=== 检查结束 ==="
log "7 天验收模板: docs/evidence/slo/acceptance-TEMPLATE.yaml"
log "k6 补量: BASE_URL=... bash scripts/observability/k6_smoke.sh --check-only"

if [[ -n "${BASE_URL}" ]] && [[ -x "${ROOT}/scripts/observability/k6_smoke.sh" ]]; then
  if bash "${ROOT}/scripts/observability/k6_smoke.sh" --check-only 2>/dev/null; then
    log "✓ k6_smoke --check-only 通过"
  else
    warn "k6_smoke --check-only 未通过（缺 k6 或 API 不可达）"
  fi
fi

if [[ "${CHECK_ONLY}" == "--check-only" ]]; then
  exit 0
fi

log "完整部署见 k8s/monitoring/STAGING_RUNBOOK.md"
