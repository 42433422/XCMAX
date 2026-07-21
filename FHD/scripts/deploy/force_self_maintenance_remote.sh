#!/usr/bin/env bash
# Remote helper: force one self-maintenance loop on the CVM (HTTP /run or in-process).
set -euo pipefail
PORT="${1:?port}"
REASON="${2:?reason}"
TOKEN="${3:-}"
base="http://127.0.0.1:${PORT}"
echo "Health:"
curl --noproxy '*' -sf --max-time 8 "${base}/api/health" | head -c 400 || true
echo
echo "Loop status (pre):"
curl --noproxy '*' -sS --max-time 20 "${base}/api/ops/self-maintenance/status?limit=5" | head -c 1500 || true
echo
code="$(curl --noproxy '*' -sS --max-time 180 -o /tmp/loop-run.json -w '%{http_code}' \
  -X POST "${base}/api/ops/self-maintenance/run" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"reason\":\"${REASON}\"}" || true)"
echo "POST /run HTTP ${code}"
head -c 2000 /tmp/loop-run.json || true
echo
if [[ "${code}" == 2* ]]; then
  echo "Loop force-run via HTTP succeeded"
  exit 0
fi
echo "HTTP /run unavailable (${code}); trying in-process python"
export LOOP_REASON="$REASON"
python3 - <<'PY'
import json, os, sys
for root in os.environ.get("LOOP_PYTHONPATHS", "").split(":"):
    root = root.strip()
    if root:
        sys.path.insert(0, root)
try:
    from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop
except Exception as exc:
    print("import_failed", repr(exc))
    sys.exit(2)
result = run_self_maintenance_loop(
    triggered_by="gha-force-self-maintenance",
    force=True,
    reason=os.environ.get("LOOP_REASON") or "gha-force-realrun",
)
print(json.dumps(result, ensure_ascii=False, default=str)[:4000])
PY
