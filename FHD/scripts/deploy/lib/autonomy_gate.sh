# shellcheck shell=bash
# Shared fail-closed bridge from deploy scripts to the domain autonomy guard.

autonomy_evaluate_action() {
  local action="${1:?autonomy action is required}"
  local action_id="${2:-deploy:${action}:$(date +%s)}"
  local deploy_root="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
  local data_dir="${XCAGI_AUTONOMY_DATA_DIR:-/var/lib/xcagi/autonomy}"
  local python_bin="${FHD_AUTONOMY_PYTHON:-${FHD_VENV:-$deploy_root/.venv}/bin/python}"
  if [[ ! -x "$python_bin" ]]; then
    python_bin="$(command -v python3)"
  fi
  install -d -m 700 "$data_dir"
  PYTHONPATH="$deploy_root" \
    XCAGI_AUTONOMY_DATA_DIR="$data_dir" \
    "$python_bin" - "$action" "$action_id" <<'PY'
import json
import os
import sys

from app.domain.autonomy.autonomy_guard import evaluate_risk

action, action_id = sys.argv[1:3]
approver = (os.environ.get("FHD_AUTONOMY_APPROVED_BY") or "").strip()
decision = evaluate_risk(
    action,
    {
        "human_approved": bool(approver),
        "approved_by": approver,
        "approval_id": (os.environ.get("FHD_AUTONOMY_APPROVAL_ID") or "").strip(),
        "trigger": "fhd_deploy_script",
    },
    action_id=action_id,
    source="fhd.deploy.script",
)
print(json.dumps(decision.to_dict(), ensure_ascii=False))
raise SystemExit(0 if decision.allowed else 42)
PY
}
