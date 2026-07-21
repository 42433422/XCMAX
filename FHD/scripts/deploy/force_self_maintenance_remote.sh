#!/usr/bin/env bash
# Remote helper: force one self-maintenance loop (prefer MODstore :8788).
set -euo pipefail
FHD_PORT="${1:?fhd_port}"
REASON="${2:?reason}"
TOKEN="${3:-}"
ADMIN_USER="${4:-admin}"
ADMIN_PASS="${5:-admin123}"

try_bases=(
  "http://127.0.0.1:8788"
  "http://127.0.0.1:${FHD_PORT}"
  "http://127.0.0.1:8765"
)

echo "Probe candidate bases:"
for base in "${try_bases[@]}"; do
  code="$(curl --noproxy '*' -sS --max-time 5 -o /tmp/ms-health.json -w '%{http_code}' "${base}/api/health" || true)"
  echo "  ${base}/api/health -> HTTP ${code}"
done

login_cookie=""
csrf=""
chosen=""
for base in "${try_bases[@]}"; do
  code="$(curl --noproxy '*' -sS --max-time 8 -o /tmp/ms-status.json -w '%{http_code}' \
    "${base}/api/ops/self-maintenance/status?limit=3" || true)"
  echo "status ${base} -> HTTP ${code}"
  if [[ "${code}" == 2* ]]; then
    chosen="$base"
    break
  fi
  # try admin login then status
  rm -f /tmp/ms-cookies.txt
  login_code="$(curl --noproxy '*' -sS --max-time 15 -c /tmp/ms-cookies.txt -b /tmp/ms-cookies.txt \
    -o /tmp/ms-login.json -w '%{http_code}' \
    -X POST "${base}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" || true)"
  echo "login ${base} -> HTTP ${login_code}"
  if [[ "${login_code}" != 2* ]]; then
    continue
  fi
  csrf="$(python3 - <<'PY'
import json
try:
    print(json.load(open("/tmp/ms-login.json")).get("csrf_token") or "")
except Exception:
    print("")
PY
)"
  code="$(curl --noproxy '*' -sS --max-time 15 -c /tmp/ms-cookies.txt -b /tmp/ms-cookies.txt \
    -o /tmp/ms-status.json -w '%{http_code}' \
    -H "X-CSRF-Token: ${csrf}" \
    "${base}/api/ops/self-maintenance/status?limit=3" || true)"
  echo "authed status ${base} -> HTTP ${code}"
  if [[ "${code}" == 2* ]]; then
    chosen="$base"
    login_cookie=1
    break
  fi
done

if [ -z "${chosen}" ]; then
  echo "No reachable self-maintenance status endpoint on candidates; listing listeners"
  ss -lntp 2>/dev/null | head -40 || netstat -lntp 2>/dev/null | head -40 || true
  docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null | head -40 || true
  exit 3
fi

echo "Using base=${chosen}"
head -c 1200 /tmp/ms-status.json || true
echo

auth_args=()
if [ -n "${TOKEN}" ]; then
  auth_args+=(-H "Authorization: Bearer ${TOKEN}")
fi
if [ -n "${login_cookie}" ]; then
  auth_args+=(-c /tmp/ms-cookies.txt -b /tmp/ms-cookies.txt)
  if [ -n "${csrf}" ]; then
    auth_args+=(-H "X-CSRF-Token: ${csrf}")
  fi
fi

code="$(curl --noproxy '*' -sS --max-time 240 -o /tmp/loop-run.json -w '%{http_code}' \
  -X POST "${chosen}/api/ops/self-maintenance/run" \
  "${auth_args[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"reason\":\"${REASON}\"}" || true)"
echo "POST /run HTTP ${code}"
head -c 3000 /tmp/loop-run.json || true
echo
if [[ "${code}" == 2* ]]; then
  echo "Loop force-run via HTTP succeeded"
  exit 0
fi

echo "HTTP /run unavailable (${code}); trying in-process python with PYTHONPATH candidates"
export LOOP_REASON="$REASON"
python3 - <<'PY'
import json, os, sys
from pathlib import Path
candidates = [
    "/opt/modstore",
    "/opt/MODstore_deploy",
    "/root/XCMAX/成都修茈科技有限公司/MODstore_deploy",
    "/root/XCMAX",
    "/opt/fhd-full",
    "/opt/fhd-staging",
]
for root in os.environ.get("LOOP_PYTHONPATHS", "").split(":") + candidates:
    root = root.strip()
    if not root:
        continue
    sys.path.insert(0, root)
    pkg = Path(root) / "modstore_server"
    if pkg.is_dir():
        print("candidate_pkg", pkg)
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
