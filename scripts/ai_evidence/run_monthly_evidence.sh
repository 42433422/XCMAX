#!/usr/bin/env bash
# AI 业务证据月度采集
#   生产/staging: DATABASE_URL=postgresql://... EVIDENCE_MONTH=2026-06
#   合成种子:     SYNTHETIC=1 bash scripts/ai_evidence/run_monthly_evidence.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MONTH="${EVIDENCE_MONTH:-$(date +%Y-%m)}"
OUT="${ROOT}/metrics/ai-evidence-${MONTH//-}.json"

if [[ "${SYNTHETIC:-}" == "1" ]]; then
  exec python3 "${ROOT}/scripts/ai_evidence/seed_synthetic_evidence.py" "${MONTH}"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: set DATABASE_URL (read-only) or SYNTHETIC=1 for seed report" >&2
  echo "Example: EVIDENCE_MONTH=2026-06 DATABASE_URL=... $0" >&2
  exit 1
fi

mkdir -p "${ROOT}/metrics"
SHIP="${ROOT}/scripts/ai_evidence/collect_shipment_audit_monthly.sql"
CON="${ROOT}/scripts/ai_evidence/collect_contract_reminder_monthly.sql"

psql "${DATABASE_URL}" -v evidence_month="${MONTH}" -f "${SHIP}" -f "${CON}" \
  | python3 -c "
import json, sys
print(json.dumps({'month':'${MONTH}','status':'psql_ok','note':'merge psql output manually'}, indent=2))
" >"$OUT"
echo "Wrote ${OUT} from DATABASE_URL"
