#!/usr/bin/env bash
# 制作线：检查 FHD ↔ MODstore 遥测/编排/文档 相关环境与服务
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

FHD_URL="${XCAGI_FHD_INTERNAL_URL:-http://127.0.0.1:5000}"
MOD_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8765}"
TELEMETRY_SECRET="${XCAGI_TELEMETRY_INGEST_SECRET:-}"

echo "== 制作线配置检查 =="
echo "FHD_URL=$FHD_URL"
echo "MOD_URL=$MOD_URL"
echo "XCAGI_TELEMETRY_INGEST_SECRET=$([ -n "$TELEMETRY_SECRET" ] && echo set || echo MISSING)"
echo "MODSTORE_CR_GIT_AUTO_PR=${MODSTORE_CR_GIT_AUTO_PR:-unset}"

fail=0
check() {
  local name="$1" url="$2"
  if curl -sf -m 8 "$url" >/dev/null; then
    echo "OK   $name"
  else
    echo "FAIL $name  $url"
    fail=1
  fi
}

check "FHD operations-line health" "$FHD_URL/api/operations-line/health"
check "MODstore health" "$MOD_URL/api/health"
check "MODstore production-line ops-health" "$MOD_URL/api/admin/production-line/operations-health"

if [[ -n "$TELEMETRY_SECRET" ]]; then
  CODE="$(curl -s -o /tmp/tel_ingest.json -w '%{http_code}' -m 8 \
    -X POST "$MOD_URL/api/internal/telemetry/ingest" \
    -H "Content-Type: application/json" \
    -H "X-Telemetry-Secret: $TELEMETRY_SECRET" \
    -d '{"signal_type":"market_signal","payload":{"description":"verify script ping"},"source":"verify"}' || echo "000")"
  if [[ "$CODE" == "200" ]]; then
    echo "OK   telemetry ingest"
  else
    echo "FAIL telemetry ingest HTTP $CODE (检查 MODstore XCAGI_TELEMETRY_INGEST_SECRET)"
    fail=1
  fi
else
  echo "WARN telemetry ingest 未测 — 设置 XCAGI_TELEMETRY_INGEST_SECRET（FHD 与 MODstore 相同）"
fi

if command -v mkdocs >/dev/null 2>&1; then
  echo "OK   mkdocs $(mkdocs --version 2>/dev/null | head -1)"
else
  echo "WARN mkdocs 未安装 — 运行: bash scripts/setup-production-line.sh"
fi

if [[ -f "$ROOT/site-docs/index.html" ]]; then
  echo "OK   site-docs/ 已构建"
else
  echo "WARN site-docs/ 不存在 — 运行: mkdocs build"
fi

exit "$fail"
