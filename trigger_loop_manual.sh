#!/usr/bin/env bash
# Manual trigger of self_maintenance_loop for 2026-07-21 P0 fix verification
# Usage: bash ~/Desktop/XCMAX/trigger_loop_manual.sh
set -uo pipefail

LOG_FILE="$HOME/Library/Logs/XCMAX/loop-trigger-manual-$(date +%Y%m%d-%H%M%S).log"
echo "[trigger] log: $LOG_FILE"
export PYTHONUNBUFFERED=1
exec > "$LOG_FILE" 2>&1

# 1. Load env snapshot, strip single quotes
set -a
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^# ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  val="${val//\'/}"
  export "$key=$val"
done < "$HOME/Library/Application Support/XCMAX/modstore-daily.env"
set +a

# 2. Override critical env vars (mirror run-modstore-daily.sh)
export MODSTORE_DAILY_ENV_CLEANROOM=1
export MODSTORE_DAILY_ROLE=scheduler
export MODSTORE_CONTROL_PORT=8788
export MODSTORE_PORT=8789
export MODSTORE_DAILY_FHD_ROOT="$HOME/XCMAX-runtime/modstore-daily/FHD"
export MODSTORE_DAILY_XCMAX_ROOT="$HOME/XCMAX-runtime/modstore-daily"
export MODSTORE_RUNTIME_ROOT="$HOME/XCMAX-runtime/modstore-daily"
export MODSTORE_RUNTIME_STATE_ROOT="$HOME/Library/Application Support/XCMAX/modstore-daily"
export MODSTORE_RUNTIME_DB_PATH="$HOME/Library/Application Support/XCMAX/modstore-daily/modstore.db"
export MODSTORE_RUNTIME_DIR="$HOME/Library/Application Support/XCMAX/modstore-daily/runtime"
export MODSTORE_DEPLOY_ROOT="$HOME/XCMAX-runtime/modstore-daily/MODstore_deploy"
export MODSTORE_REPO_ROOT="$HOME/XCMAX-runtime/modstore-daily/MODstore_deploy"
export MODSTORE_DB_PATH="$HOME/Library/Application Support/XCMAX/modstore-daily/modstore.db"
export DATABASE_URL="sqlite:////Users/a4243342/Library/Application Support/XCMAX/modstore-daily/modstore.db"
# 注意：sqlite URL 必须 4 个 slash 才是绝对路径，3 个 slash 会变成相对路径连到空 DB
export PYTHONPATH="$HOME/XCMAX-runtime/modstore-daily/MODstore_deploy:$HOME/XCMAX-runtime/modstore-daily/packages/xcagi_common"
export XCAGI_FHD_ROOT="$HOME/XCMAX-runtime/modstore-daily/FHD"
export XCMAX_MONOREPO_ROOT="$HOME/XCMAX-runtime/modstore-daily"
# Source checkout (complete FHD SSOT). ensure_fhd_on_path falls back here when
# the runtime FHD mirror lags (e.g. missing app/domain/autonomy/).
export MODSTORE_GIT_REPO_ROOT="$HOME/Desktop/XCMAX"
export MODSTORE_DAILY_XCMAX_ROOT="$HOME/Desktop/XCMAX"
export XCAGI_FHD_RUNTIME_ROOT="$HOME/Desktop/XCMAX/FHD"

cd "$HOME/XCMAX-runtime/modstore-daily/MODstore_deploy"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] trigger start"
echo "[trigger] env: MODSTORE_RUNTIME_DIR=$MODSTORE_RUNTIME_DIR"
echo "[trigger] env: DATABASE_URL=$DATABASE_URL"
echo "[trigger] env: PYTHONPATH=$PYTHONPATH"
echo "[trigger] env: MODSTORE_RUNTIME_DB_PATH=$MODSTORE_RUNTIME_DB_PATH"

"$HOME/XCMAX-runtime/modstore-daily/MODstore_deploy/.venv/bin/python" <<'PYEOF'
import json, sys, traceback, os
try:
    print(f"[python] MODSTORE_RUNTIME_DIR={os.environ.get('MODSTORE_RUNTIME_DIR')}")
    print(f"[python] DATABASE_URL={os.environ.get('DATABASE_URL')}")
    from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop
    print("[python] module imported OK, calling run_self_maintenance_loop(force=True)...")
    result = run_self_maintenance_loop(
        triggered_by="manual",
        force=True,
        reason="manual verify 2026-07-21 P0 employee quality prompt fix"
    )
    print("===RESULT===")
    print(json.dumps(result, default=str, indent=2, ensure_ascii=False))
except Exception:
    print("===EXCEPTION===")
    traceback.print_exc()
    sys.exit(1)
PYEOF
EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] trigger end (exit=$EXIT)"
echo "[trigger] full log saved to: $LOG_FILE"
