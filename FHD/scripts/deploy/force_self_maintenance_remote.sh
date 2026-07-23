#!/usr/bin/env bash
# Remote helper: force one self-maintenance loop on CVM.
# Production MODstore listens on :9999/:9990 (not :8788).
set -euo pipefail
FHD_PORT="${1:?fhd_port}"
REASON_FILE="${2:?reason_file}"
TOKEN_FILE="${3:-}"
ADMIN_USER="${4:-admin}"
ADMIN_PASS="${5:-admin123}"

# Secrets and workflow-dispatch input must never be embedded in the SSH command
# line.  The workflow uploads mode-0600 files with constrained names; consume
# and remove them before starting the long-running loop.
if [[ ! -r "$REASON_FILE" || "$REASON_FILE" != /tmp/xcmax-force-loop-*.reason ]]; then
  echo "Invalid or unreadable reason file" >&2
  exit 2
fi
REASON="$(<"$REASON_FILE")"
TOKEN=""
if [ -n "$TOKEN_FILE" ]; then
  if [[ ! -r "$TOKEN_FILE" || "$TOKEN_FILE" != /tmp/xcmax-force-loop-*.token ]]; then
    echo "Invalid or unreadable token file" >&2
    exit 2
  fi
  TOKEN="$(<"$TOKEN_FILE")"
fi
rm -f -- "$REASON_FILE"
[ -z "$TOKEN_FILE" ] || rm -f -- "$TOKEN_FILE"

try_bases=(
  "http://127.0.0.1:9999"
  "http://127.0.0.1:9990"
  "http://127.0.0.1:8788"
  "http://127.0.0.1:8765"
  "http://127.0.0.1:${FHD_PORT}"
  "http://127.0.0.1:5100"
  "http://127.0.0.1:5101"
)

echo "Probe candidate bases:"
for base in "${try_bases[@]}"; do
  code="$(curl --noproxy '*' -sS --max-time 5 -o /tmp/ms-health.json -w '%{http_code}' "${base}/api/health" || true)"
  echo "  ${base}/api/health -> HTTP ${code}"
done

BEARER_TOKEN=""
CHOSEN_BASE=""

choose_base_via_http() {
  local base code ok_flag
  for base in "${try_bases[@]}"; do
    code="$(curl --noproxy '*' -sS --max-time 8 -o /tmp/ms-status.json -w '%{http_code}' \
      "${base}/api/ops/self-maintenance/status?limit=3" || true)"
    ok_flag="$(python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/ms-status.json"))
except Exception:
    print("0")
    raise SystemExit(0)
# FHD catch-all may return HTTP 200 + success:false for missing ops routes.
if d.get("ok") is True or d.get("success") is True:
    print("1")
elif isinstance(d.get("cron"), dict) or d.get("memory") is not None:
    print("1")
else:
    print("0")
PY
)"
    echo "status ${base} -> HTTP ${code} ok_flag=${ok_flag}"
    if [[ "${code}" == 2* && "${ok_flag}" == "1" ]]; then
      CHOSEN_BASE="$base"
      return 0
    fi
  done
  return 1
}

ensure_bearer_token() {
  local base="$1"
  local login_code
  login_code="$(curl --noproxy '*' -sS --max-time 15 -o /tmp/ms-login.json -w '%{http_code}' \
    -X POST "${base}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" || true)"
  echo "login ${base} -> HTTP ${login_code}"
  [[ "${login_code}" == 2* ]] || return 1
  BEARER_TOKEN="$(python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/ms-login.json"))
    print(d.get("access_token") or d.get("token") or "")
except Exception:
    print("")
PY
)"
  [ -n "${BEARER_TOKEN}" ]
}

post_run_http() {
  local base="$1"
  local auth_args=()
  if [ -n "${BEARER_TOKEN}" ]; then
    auth_args+=(-H "Authorization: Bearer ${BEARER_TOKEN}")
  elif [ -n "${TOKEN}" ]; then
    auth_args+=(-H "Authorization: Bearer ${TOKEN}")
  fi
  local code ok_run
  code="$(curl --noproxy '*' -sS --max-time 2400 -o /tmp/loop-run.json -w '%{http_code}' \
    -X POST "${base}/api/ops/self-maintenance/run" \
    "${auth_args[@]}" \
    -H "Content-Type: application/json" \
    -d "{\"reason\":\"${REASON}\"}" || true)"
  echo "POST /run HTTP ${code}"
  head -c 3000 /tmp/loop-run.json || true
  echo
  [[ "${code}" == 2* ]] || return 1
  # HTTP 200 + skipped_active_lease must not count as success.
  ok_run="$(python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/loop-run.json"))
except Exception:
    print("0")
    raise SystemExit(0)
result = d.get("result") if isinstance(d, dict) else None
status = ""
if isinstance(result, dict):
    status = str(result.get("status") or "")
elif isinstance(d, dict):
    status = str(d.get("status") or "")
success = status == "completed" or status.startswith("completed_")
print("1" if success else "0")
PY
)"
  [[ "${ok_run}" == "1" ]]
}

run_inprocess_with_live_env() {
  # Prefer env from live modstore uvicorn (ports 9999/9990).
  local pid mod py
  pid="$(pgrep -af 'uvicorn modstore_server.app:app' | awk 'NR==1{print $1}' || true)"
  mod="$(ls -d /opt/xcmax/current/*/MODstore_deploy 2>/dev/null | head -1 || true)"
  [ -n "$mod" ] || mod="$(ls -d /root/*/MODstore_deploy 2>/dev/null | head -1 || true)"
  [ -n "$mod" ] || return 1
  # System python3 often lacks apscheduler; prefer deploy venv.
  py="${mod}/.venv/bin/python"
  [ -x "$py" ] || py="$(command -v python3)"
  export LOOP_REASON="$REASON"
  export LOOP_MOD="$mod"
  export LOOP_PID="${pid:-}"
  "$py" - <<'PY'
import json, os, sys
from pathlib import Path

mod = os.environ["LOOP_MOD"]
pid = (os.environ.get("LOOP_PID") or "").strip()
if pid and Path(f"/proc/{pid}/environ").exists():
    env = {}
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if not item or b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        env[k.decode()] = v.decode(errors="replace")
    for k, v in env.items():
        os.environ[k] = v
# Break-glass: production worktree is often dirty vs PARA branch=main.
os.environ["MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME"] = "0"
# Force path: don't stall when Mac already has a codex currentTask.
os.environ["MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE"] = "1"
os.environ["MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC"] = os.environ.get(
    "MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", "15"
)
# PARA dispatches to Mac agents that need HTTPS GitHub URLs (SSH host aliases are CVM-only).
os.environ["MODSTORE_PARA_REPO_URL"] = "https://github.com/42433422/XCMAX.git"
os.environ["MODSTORE_PARA_SKIP_GIT_PREFLIGHT"] = "1"
if not (os.environ.get("GIT_SSH_COMMAND") or "").strip():
    key = Path("/root/.ssh/xcagi_modstore_deploy")
    if key.exists():
        os.environ["GIT_SSH_COMMAND"] = (
            f"ssh -i {key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
sys.path.insert(0, mod)
os.chdir(mod)
from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop

result = run_self_maintenance_loop(
    triggered_by="gha-force-self-maintenance",
    force=True,
    reason=os.environ.get("LOOP_REASON") or "gha-force-realrun",
)
print(json.dumps(result, ensure_ascii=False, default=str)[:4000])
status = str(result.get("status") or "")
success = status == "completed" or status.startswith("completed_")
raise SystemExit(0 if success else 3)
PY
}

# Prefer known MODstore listeners even when /status probe was flaky.
preferred_http_bases=(
  "http://127.0.0.1:9999"
  "http://127.0.0.1:9990"
)

# Run outside the API worker first.  Self-maintenance can deploy and restart
# MODstore; an HTTP request hosted by that same service would be terminated in
# the middle of its own deployment and then retried as a duplicate run.
echo "Trying in-process loop with live production env first"
if run_inprocess_with_live_env; then
  echo "Loop force-run via in-process python succeeded"
  exit 0
fi

echo "In-process force-run unavailable; trying authenticated HTTP fallbacks"
if choose_base_via_http; then
  echo "Using base=${CHOSEN_BASE}"
  head -c 1200 /tmp/ms-status.json || true
  echo
  ensure_bearer_token "$CHOSEN_BASE" || true
  if post_run_http "$CHOSEN_BASE"; then
    echo "Loop force-run via HTTP succeeded"
    exit 0
  fi
  echo "HTTP /run unavailable on chosen base; trying preferred MODstore ports"
fi

for base in "${preferred_http_bases[@]}"; do
  ensure_bearer_token "$base" || true
  if post_run_http "$base"; then
    echo "Loop force-run via HTTP succeeded on ${base}"
    exit 0
  fi
done

echo "All force-run strategies failed; dumping listeners/containers"
ss -lntp 2>/dev/null | head -60 || true
docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null | head -40 || true
exit 3
