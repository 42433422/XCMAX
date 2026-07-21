#!/usr/bin/env bash
# Force one auditable local self-maintenance loop from the installed exact runtime.
set -euo pipefail

RUNTIME_ROOT="${MODSTORE_LOCAL_RUNTIME_ROOT:-/Users/a4243342/XCMAX-runtime/modstore-daily}"
STATE_ROOT="${MODSTORE_LOCAL_STATE_ROOT:-/Users/a4243342/Library/Application Support/XCMAX/modstore-daily}"
ENV_SNAPSHOT="${MODSTORE_LOCAL_ENV_FILE:-/Users/a4243342/Library/Application Support/XCMAX/modstore-daily.env}"
MANIFEST="$RUNTIME_ROOT/.xcmax-runtime-provenance.json"
LOG_DIR="${MODSTORE_LOCAL_LOG_DIR:-/Users/a4243342/Library/Logs/XCMAX}"
LOG_FILE="$LOG_DIR/loop-trigger-manual-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOG_DIR"
echo "[trigger] log: $LOG_FILE"
exec >"$LOG_FILE" 2>&1

if [[ -f "$ENV_SNAPSHOT" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_SNAPSHOT"
  set +a
fi
[[ -f "$MANIFEST" ]] || { echo "[trigger] runtime provenance manifest missing" >&2; exit 2; }
RUNTIME_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_sha"])' "$MANIFEST")"
[[ "$RUNTIME_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "[trigger] invalid runtime SHA" >&2; exit 2; }

export PYTHONUNBUFFERED=1
export MODSTORE_DAILY_ENV_CLEANROOM=1
export MODSTORE_DAILY_ROLE=scheduler
# A manual self-maintenance verification must not enqueue unrelated incident teams.
export MODSTORE_INCIDENT_TEAM_ENABLED=0
export MODSTORE_RUNTIME_ROOT="$RUNTIME_ROOT"
export MODSTORE_RUNTIME_STATE_ROOT="$STATE_ROOT"
export MODSTORE_RUNTIME_DB_PATH="$STATE_ROOT/modstore.db"
export MODSTORE_RUNTIME_DIR="$STATE_ROOT/runtime"
export MODSTORE_CATALOG_DIR="$STATE_ROOT/catalog"
export MODSTORE_DEPLOY_ROOT="$RUNTIME_ROOT/MODstore_deploy"
export MODSTORE_REPO_ROOT="$RUNTIME_ROOT/MODstore_deploy"
export MODSTORE_DB_PATH="$STATE_ROOT/modstore.db"
export DATABASE_URL="sqlite:///$MODSTORE_RUNTIME_DB_PATH"
export PYTHONPATH="$RUNTIME_ROOT/MODstore_deploy:$RUNTIME_ROOT/packages/xcagi_common"
export XCAGI_FHD_ROOT="$RUNTIME_ROOT/FHD"
export XCAGI_FHD_RUNTIME_ROOT="$RUNTIME_ROOT/FHD"
export XCMAX_MONOREPO_ROOT="$RUNTIME_ROOT"
export MODSTORE_GIT_SHA="$RUNTIME_SHA"
export MODSTORE_EXPECTED_GIT_SHA="$RUNTIME_SHA"
export MODSTORE_RELEASE_MANIFEST="$MANIFEST"
export MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME=1

cd "$RUNTIME_ROOT/MODstore_deploy"
"$RUNTIME_ROOT/MODstore_deploy/.venv/bin/python" <<'PY'
import json
from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop

result = run_self_maintenance_loop(
    triggered_by="manual",
    force=True,
    reason="manual exact-runtime self-maintenance verification",
)
print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
PY
