#!/usr/bin/env bash
# Round-2 staging k6 7d SLO contract — prepare ConfigMap/Job and optionally start after round-1 finishes.
#
# Usage (from repo root):
#   bash FHD/scripts/observability/launch_k6_round2_staging.sh --preflight
#   bash FHD/scripts/observability/launch_k6_round2_staging.sh --prepare     # safe while round-1 still running
#   bash FHD/scripts/observability/launch_k6_round2_staging.sh --start       # stop round-1 job + start round-2
#
# Env:
#   XCMAX_REMOTE_HOST=119.27.178.147
#   K6_NAMESPACE=xcagi-staging
#   E2E_USER / E2E_PASSWORD (default admin / admin123)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE="${XCMAX_REMOTE_HOST:-119.27.178.147}"
NS="${K6_NAMESPACE:-xcagi-staging}"
SSH="ssh -o ConnectTimeout=10 -o BatchMode=yes root@${REMOTE}"
SCP="scp -o ConnectTimeout=10 -o BatchMode=yes"
REMOTE_KUB="/usr/local/bin/k3s kubectl"
REMOTE_DIR="/opt/xcagi-k8s-round2"
E2E_USER="${E2E_USER:-admin}"
E2E_PASSWORD="${E2E_PASSWORD:-admin123}"

MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --preflight) MODE=preflight; shift ;;
    --prepare) MODE=prepare; shift ;;
    --start) MODE=start; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$MODE" ]]; then
  echo "Specify --preflight | --prepare | --start" >&2
  exit 1
fi

log() { printf '[k6-round2] %s\n' "$*"; }

sync_manifests_locally() {
  bash "${ROOT}/scripts/observability/sync_k6_configmap.sh" \
    --namespace "$NS" \
    --output "${ROOT}/k8s/monitoring/k6-configmap.yaml"
}

upload_manifests() {
  sync_manifests_locally
  $SSH "mkdir -p ${REMOTE_DIR}"
  $SCP "${ROOT}/k8s/monitoring/k6-configmap.yaml" "root@${REMOTE}:${REMOTE_DIR}/"
  $SCP "${ROOT}/k8s/monitoring/k6-7day-job.yaml" "root@${REMOTE}:${REMOTE_DIR}/"
  log "uploaded manifests to ${REMOTE}:${REMOTE_DIR}/"
}

remote_preflight() {
  $SSH bash -s <<EOF
set -euo pipefail
NS=${NS}
KUB='${REMOTE_KUB}'
BASE="http://127.0.0.1:30080"
E2E_USER="${E2E_USER}"
E2E_PASSWORD="${E2E_PASSWORD}"

echo "=== cluster pods ==="
\$KUB -n \$NS get pods

echo "=== round-1 k6 status ==="
\$KUB -n \$NS get job k6-7day -o wide 2>/dev/null || echo "(no k6-7day job)"

echo "=== API smoke (health + login + stream) ==="
export BASE E2E_USER E2E_PASSWORD
python3 <<PY
import json, urllib.request, http.cookiejar, os

base = os.environ["BASE"]
user = os.environ["E2E_USER"]
password = os.environ["E2E_PASSWORD"]
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
health = opener.open(base + "/api/health")
csrf = next((c.value for c in cj if "csrf" in c.name.lower()), "")
headers = {"Content-Type": "application/json"}
if csrf:
    headers["X-CSRF-Token"] = csrf
login_body = json.dumps({"username": user, "password": password, "account_kind": "personal"}).encode()
login = opener.open(urllib.request.Request(base + "/api/auth/login", data=login_body, method="POST", headers=headers))
print("health", health.status, "login", login.status)
stream = opener.open(urllib.request.Request(
    base + "/api/ai/chat/stream",
    data=json.dumps({"message": "round2 preflight"}).encode(),
    method="POST",
    headers=headers,
))
chunk = stream.read(80)
print("stream", stream.status, chunk[:60])
PY

echo "=== prometheus target ==="
curl -sf http://127.0.0.1:30090/api/v1/targets \\
  | python3 -c "import sys,json; d=json.load(sys.stdin); ts=d['data']['activeTargets']; print([(t['labels'].get('job'), t['health']) for t in ts])"

echo "=== SSOT configmap present? ==="
\$KUB -n \$NS get configmap k6-7day-contract -o name 2>/dev/null || echo "k6-7day-contract: MISSING"
\$KUB -n \$NS get configmap k6-script -o name 2>/dev/null || echo "k6-script (legacy): absent"
EOF
}

remote_prepare() {
  upload_manifests
  $SSH bash -s <<EOF
set -euo pipefail
NS=${NS}
KUB='${REMOTE_KUB}'
DIR=${REMOTE_DIR}

echo "=== apply SSOT ConfigMap (does not restart running Job) ==="
\$KUB apply -f "\$DIR/k6-configmap.yaml"

echo "=== ensure e2e secret (optional override) ==="
\$KUB -n \$NS create secret generic xcagi-e2e-creds \\
  --from-literal=username='${E2E_USER}' \\
  --from-literal=password='${E2E_PASSWORD}' \\
  --dry-run=client -o yaml | \$KUB apply -f -

echo "=== legacy placeholder ConfigMap (k6-script) — keep for reference, round-2 uses k6-7day-contract ==="
\$KUB -n \$NS get configmap k6-script -o yaml 2>/dev/null | head -5 || true

echo "=== round-2 job manifest ready (NOT applied until --start) ==="
grep -E 'XCAGI_BASE_URL|k6_7d_contract' "\$DIR/k6-7day-job.yaml" || true

echo "=== DONE prepare — wait for round-1 k6-7day to finish, then run --start ==="
\$KUB -n \$NS get job k6-7day -o jsonpath='{.status.active}{" active, "}{.status.succeeded}{" succeeded\\n"}' 2>/dev/null || true
EOF
  log "prepare complete on ${REMOTE}"
}

remote_start() {
  upload_manifests
  $SSH bash -s <<EOF
set -euo pipefail
NS=${NS}
KUB='${REMOTE_KUB}'
DIR=${REMOTE_DIR}

ACTIVE=\$(\$KUB -n \$NS get job k6-7day -o jsonpath='{.status.active}' 2>/dev/null || echo "")
if [[ -n "\$ACTIVE" && "\$ACTIVE" != "0" ]]; then
  echo "ERROR: k6-7day still active (round-1 running). Wait for 168h completion or confirm abort." >&2
  \$KUB -n \$NS get job k6-7day
  exit 1
fi

echo "=== delete finished / stale k6 job ==="
\$KUB -n \$NS delete job k6-7day --ignore-not-found

echo "=== apply SSOT ConfigMap + Job ==="
\$KUB apply -f "\$DIR/k6-configmap.yaml"
\$KUB apply -f "\$DIR/k6-7day-job.yaml"

echo "=== wait for k6 pod ==="
for i in \$(seq 1 30); do
  PHASE=\$(\$KUB -n \$NS get pods -l job-name=k6-7day -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)
  echo "attempt \$i phase=\$PHASE"
  [[ "\$PHASE" == "Running" ]] && break
  sleep 5
done

echo "=== k6 logs (first 20 lines) ==="
\$KUB -n \$NS logs job/k6-7day --tail=20 2>/dev/null || true

echo "=== job status ==="
\$KUB -n \$NS get job k6-7day -o wide
\$KUB -n \$NS get pods -l job-name=k6-7day

echo ""
echo "Round-2 started. After 168h run on server:"
echo "  PROMETHEUS_URL=http://127.0.0.1:30090 GRAFANA_URL=http://127.0.0.1:30300 \\"
echo "    bash /opt/fhd-full/scripts/observability/run_staging_7d_acceptance.sh --prefix staging"
EOF
  log "round-2 k6 job started on ${REMOTE}"
}

case "$MODE" in
  preflight) remote_preflight ;;
  prepare) remote_prepare ;;
  start) remote_start ;;
esac
