#!/usr/bin/env bash
# k6 冒烟占位：对 BASE_URL 跑 scripts/loadtest/smoke.js（T36–T37 流量补量）
# 不伪造结果；未设 BASE_URL 或不可达时退出非 0。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SMOKE_JS="${ROOT}/scripts/loadtest/smoke.js"
BASE_URL="${BASE_URL:-}"
CHECK_ONLY=false

log() { printf '[k6_smoke] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
用法: bash scripts/observability/k6_smoke.sh [--check-only]

  对 staging 或本地 API 运行 k6 smoke（复用 scripts/loadtest/smoke.js）。

  --check-only  仅检查 k6 / 脚本路径 / BASE_URL 可达性，不执行压测

环境变量:
  BASE_URL   必填（staging 示例: https://api.staging.example）
  K6_OUT     可选，k6 结果 JSON 输出路径（默认: scripts/loadtest/results-smoke.json）
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --check-only) CHECK_ONLY=true; shift ;;
    *) fail "未知参数: $1（见 --help）" ;;
  esac
done

[[ -f "${SMOKE_JS}" ]] || fail "缺少 ${SMOKE_JS}"
command -v k6 >/dev/null 2>&1 || fail "未安装 k6。见 https://grafana.com/docs/k6/latest/set-up/install-k6/"

if [[ -z "${BASE_URL}" ]]; then
  fail "请设置 BASE_URL（staging API 根 URL，勿用 localhost 冒充 staging 验收）"
fi

if ! curl -sf "${BASE_URL}/api/health" >/dev/null 2>&1; then
  fail "${BASE_URL}/api/health 不可达。确认 API 与网络/VPN 后再跑。"
fi

log "前置检查通过: k6=$(k6 version 2>/dev/null | head -1) BASE_URL=${BASE_URL}"

if [[ "${CHECK_ONLY}" == true ]]; then
  log "--check-only：未执行 k6 run。"
  exit 0
fi

K6_OUT="${K6_OUT:-${ROOT}/scripts/loadtest/results-smoke.json}"
log "开始 k6 smoke → 结果写入 ${K6_OUT}"
cd "${ROOT}"
k6 run --summary-export="${K6_OUT}" "${SMOKE_JS}"
log "完成。压测期间请在 Grafana xcagi-api-overview 观察 P95 / 错误率。"
