#!/usr/bin/env bash
# 检查运营线相关环境与服务连通性（本地默认 FHD:5000 / MODstore:8765）
set -euo pipefail

FHD_URL="${XCAGI_FHD_INTERNAL_URL:-http://127.0.0.1:5000}"
MOD_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8765}"
SECRET="${XCAGI_CS_INTAKE_WEBHOOK_SECRET:-xcagi-cs-intake-dev-secret}"

echo "== 运营线配置检查 =="
echo "FHD_URL=$FHD_URL"
echo "MOD_URL=$MOD_URL"
echo "WEBHOOK_SECRET=${SECRET:0:8}..."

check() {
  local name="$1" url="$2"
  if curl -sf -m 5 "$url" >/dev/null; then
    echo "OK  $name  $url"
  else
    echo "FAIL $name  $url (服务未启动或路径不对)"
    return 1
  fi
}

fail=0
check "FHD health" "$FHD_URL/api/operations-line/health" || fail=1
check "MODstore health" "$MOD_URL/api/health" || fail=1
check "MODstore ops-health" "$MOD_URL/api/admin/production-line/operations-health" || fail=1

echo ""
echo "== CRM 数据目录 =="
CRM="$(
  cd "$(dirname "$0")/.." && pwd
)/data/customer_service/crm.sqlite3"
if [[ -f "$CRM" ]]; then
  echo "OK  crm.sqlite3 exists ($CRM)"
else
  echo "WARN crm.sqlite3 missing — 运行: python3 scripts/backfill_cs_crm_from_pipelines.py"
fi

echo ""
echo "== Pipeline CRM/ERP 缺口（可选 STRICT=1 失败退出）=="
HEALTH_JSON="$(curl -sf -m 8 "$FHD_URL/api/operations-line/health" 2>/dev/null || echo '{}')"
MISSING="$(echo "$HEALTH_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('data') or {}; print(int(d.get('breakpoint_count') or 0))" 2>/dev/null || echo "?")"
echo "breakpoint_count=$MISSING"
if [[ "${STRICT:-0}" == "1" && "$MISSING" != "0" ]]; then
  echo "FAIL strict: CRM/ERP gaps remain — run backfill or repair-all"
  fail=1
fi

exit "$fail"
