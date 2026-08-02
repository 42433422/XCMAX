#!/usr/bin/env bash
# Install an exact clean XCMAX commit into the local MODstore autonomy runtime.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TARGET_ROOT="${MODSTORE_LOCAL_RUNTIME_ROOT:-/Users/a4243342/XCMAX-runtime/modstore-daily}"
TARGET_SHA="${XCMAX_TARGET_SHA:-$(git -C "$SOURCE_ROOT" rev-parse HEAD)}"
ENV_FILE="${MODSTORE_LOCAL_ENV_FILE:-/Users/a4243342/Library/Application Support/XCMAX/modstore-daily.env}"
MANIFEST="$TARGET_ROOT/.xcmax-runtime-provenance.json"
LOCK_FILE="${MODSTORE_LOCAL_INSTALL_LOCK:-/tmp/xcmax-local-autonomy-runtime.lock}"
LOCK_DIR="${LOCK_FILE}.d"
LAUNCHCTL_BIN="${MODSTORE_LAUNCHCTL_BIN:-launchctl}"
CURL_BIN="${MODSTORE_CURL_BIN:-curl}"
HEALTH_ATTEMPTS="${MODSTORE_INSTALL_HEALTH_ATTEMPTS:-30}"
HEALTH_SLEEP_SECONDS="${MODSTORE_INSTALL_HEALTH_SLEEP_SECONDS:-2}"
RUNTIME_FILE_RELATIVES=(
  "FHD/app/application/employee_runtime/risk_gate.py"
  "FHD/app/services/capability_proposal_recorder.py"
  "FHD/app/services/intent_confirmation_service.py"
  "FHD/config/duty_employee_work_contracts.json"
  "FHD/config/risk_actions.registry.json"
  "FHD/scripts/dev/capability_proposal_to_issue.py"
)

[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "[install] invalid exact SHA" >&2; exit 2; }
[[ "$HEALTH_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] \
  || { echo "[install] invalid health attempts" >&2; exit 2; }
[[ "$HEALTH_SLEEP_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]] \
  || { echo "[install] invalid health sleep seconds" >&2; exit 2; }
[[ "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" == "$TARGET_SHA" ]] \
  || { echo "[install] source HEAD does not equal target SHA" >&2; exit 2; }
[[ -z "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=normal)" ]] \
  || { echo "[install] source checkout must be clean" >&2; exit 2; }
case "$TARGET_ROOT" in
  /Users/*/XCMAX-runtime/modstore-daily) ;;
  *)
    [[ "${MODSTORE_ALLOW_CUSTOM_LOCAL_RUNTIME_ROOT:-0}" == 1 ]] \
      || { echo "[install] custom target requires explicit opt-in" >&2; exit 2; }
    ;;
esac
[[ -d "$TARGET_ROOT/MODstore_deploy" && -d "$TARGET_ROOT/FHD" ]] \
  || { echo "[install] runtime target is incomplete: $TARGET_ROOT" >&2; exit 2; }

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  ACTIVE_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$ACTIVE_PID" =~ ^[0-9]+$ ]] && kill -0 "$ACTIVE_PID" 2>/dev/null; then
    echo "[install] another runtime install is active pid=$ACTIVE_PID" >&2
    exit 3
  fi
  mv "$LOCK_DIR" "${LOCK_DIR}.stale.$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"

STAGE="$(mktemp -d /tmp/xcmax-local-runtime-stage.XXXXXX)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$TARGET_ROOT/.runtime-backups/$STAMP"
mkdir -p "$BACKUP"
cleanup() { rm -rf -- "$STAGE"; rm -f -- "$LOCK_DIR/pid"; rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA" | tar -xf - -C "$STAGE"
SOURCE_MODSTORE="$STAGE/成都修茈科技有限公司/MODstore_deploy/modstore_server"
SOURCE_ALEMBIC="$STAGE/成都修茈科技有限公司/MODstore_deploy/alembic"
SOURCE_AUTONOMY="$STAGE/FHD/app/domain/autonomy"
SOURCE_EMPLOYEES="$STAGE/FHD/mods/_employees"
[[ -f "$SOURCE_MODSTORE/self_maintenance_loop_runner.py" ]] \
  || { echo "[install] staged MODstore source missing" >&2; exit 4; }
[[ -f "$SOURCE_ALEMBIC/env.py" ]] \
  || { echo "[install] staged Alembic source missing" >&2; exit 4; }
[[ -f "$SOURCE_AUTONOMY/autonomy_guard.py" ]] \
  || { echo "[install] staged FHD autonomy source missing" >&2; exit 4; }
[[ -f "$SOURCE_EMPLOYEES/host-checker/manifest.json" ]] \
  || { echo "[install] staged duty employee source missing" >&2; exit 4; }
for relative in "${RUNTIME_FILE_RELATIVES[@]}"; do
  [[ -f "$STAGE/$relative" ]] \
    || { echo "[install] staged runtime file missing: $relative" >&2; exit 4; }
done

rsync -a "$TARGET_ROOT/MODstore_deploy/modstore_server/" "$BACKUP/modstore_server/"
rsync -a "$TARGET_ROOT/FHD/app/domain/autonomy/" "$BACKUP/autonomy/"
if [[ -d "$TARGET_ROOT/FHD/mods/_employees" ]]; then
  rsync -a "$TARGET_ROOT/FHD/mods/_employees/" "$BACKUP/employees/"
else
  touch "$BACKUP/employees.absent"
fi
if [[ -d "$TARGET_ROOT/MODstore_deploy/alembic" ]]; then
  rsync -a "$TARGET_ROOT/MODstore_deploy/alembic/" "$BACKUP/alembic/"
else
  touch "$BACKUP/alembic.absent"
fi
for relative in "${RUNTIME_FILE_RELATIVES[@]}"; do
  backup_file="$BACKUP/files/$relative"
  mkdir -p "$(dirname "$backup_file")"
  if [[ -f "$TARGET_ROOT/$relative" ]]; then
    cp -p "$TARGET_ROOT/$relative" "$backup_file"
  else
    touch "${backup_file}.absent"
  fi
done
[[ -f "$MANIFEST" ]] && cp -p "$MANIFEST" "$BACKUP/runtime-provenance.json"
[[ -f "$ENV_FILE" ]] && cp -p "$ENV_FILE" "$BACKUP/modstore-daily.env"

rollback() {
  trap - ERR
  echo "[install] failed; restoring $BACKUP" >&2
  rsync -a --delete "$BACKUP/modstore_server/" "$TARGET_ROOT/MODstore_deploy/modstore_server/"
  rsync -a --delete "$BACKUP/autonomy/" "$TARGET_ROOT/FHD/app/domain/autonomy/"
  if [[ -f "$BACKUP/employees.absent" ]]; then
    rm -rf -- "$TARGET_ROOT/FHD/mods/_employees"
  else
    mkdir -p "$TARGET_ROOT/FHD/mods/_employees"
    rsync -a --delete "$BACKUP/employees/" "$TARGET_ROOT/FHD/mods/_employees/"
  fi
  if [[ -f "$BACKUP/alembic.absent" ]]; then
    rm -rf -- "$TARGET_ROOT/MODstore_deploy/alembic"
  else
    mkdir -p "$TARGET_ROOT/MODstore_deploy/alembic"
    rsync -a --delete "$BACKUP/alembic/" "$TARGET_ROOT/MODstore_deploy/alembic/"
  fi
  for relative in "${RUNTIME_FILE_RELATIVES[@]}"; do
    backup_file="$BACKUP/files/$relative"
    target_file="$TARGET_ROOT/$relative"
    if [[ -f "${backup_file}.absent" ]]; then
      rm -f -- "$target_file"
    else
      mkdir -p "$(dirname "$target_file")"
      cp -p "$backup_file" "$target_file"
    fi
  done
  if [[ -f "$BACKUP/runtime-provenance.json" ]]; then
    cp -p "$BACKUP/runtime-provenance.json" "$MANIFEST"
  else
    mv -f "$MANIFEST" "$BACKUP/failed-runtime-provenance.json" 2>/dev/null || true
  fi
  [[ -f "$BACKUP/modstore-daily.env" ]] && cp -p "$BACKUP/modstore-daily.env" "$ENV_FILE"
  for label in com.xcmax.modstore-daily com.xcmax.modstore-scheduler; do
    target="gui/$(id -u)/$label"
    "$LAUNCHCTL_BIN" print "$target" >/dev/null 2>&1 \
      && "$LAUNCHCTL_BIN" kickstart -k "$target" || true
  done
}
trap rollback ERR

rsync -a --delete --exclude '__pycache__/' "$SOURCE_MODSTORE/" \
  "$TARGET_ROOT/MODstore_deploy/modstore_server/"
mkdir -p "$TARGET_ROOT/MODstore_deploy/alembic"
rsync -a --delete --exclude '__pycache__/' "$SOURCE_ALEMBIC/" \
  "$TARGET_ROOT/MODstore_deploy/alembic/"
rsync -a --delete --exclude '__pycache__/' "$SOURCE_AUTONOMY/" \
  "$TARGET_ROOT/FHD/app/domain/autonomy/"
mkdir -p "$TARGET_ROOT/FHD/mods/_employees"
rsync -a --delete --exclude '__pycache__/' "$SOURCE_EMPLOYEES/" \
  "$TARGET_ROOT/FHD/mods/_employees/"
for relative in "${RUNTIME_FILE_RELATIVES[@]}"; do
  target_file="$TARGET_ROOT/$relative"
  mkdir -p "$(dirname "$target_file")"
  cp -p "$STAGE/$relative" "$target_file"
done

python3 - "$TARGET_ROOT" "$TARGET_SHA" "$MANIFEST" <<'PY'
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

root, git_sha, manifest = sys.argv[1:]
files = [
    "MODstore_deploy/alembic/env.py",
    "MODstore_deploy/alembic/versions/20260512_consolidate_init_db_columns.py",
    "MODstore_deploy/alembic/versions/20260722_autonomy_decision_audit.py",
    "MODstore_deploy/alembic/versions/20260722_customer_value_receipts.py",
    "MODstore_deploy/alembic/versions/20260722_outbox_dlq_resolution.py",
    "MODstore_deploy/modstore_server/api/admin_events.py",
    "MODstore_deploy/modstore_server/api/app_factory.py",
    "MODstore_deploy/modstore_server/admin_employee_autonomy_api.py",
    "MODstore_deploy/modstore_server/autonomy_decision_audit.py",
    "MODstore_deploy/modstore_server/autonomy_decision_evidence_api.py",
    "MODstore_deploy/modstore_server/autonomy_guard_delegate.py",
    "MODstore_deploy/modstore_server/autonomy_posthoc_auditor.py",
    "MODstore_deploy/modstore_server/customer_value_evidence.py",
    "MODstore_deploy/modstore_server/customer_value_evidence_api.py",
    "MODstore_deploy/modstore_server/customer_value_reconciler.py",
    "MODstore_deploy/modstore_server/db/alembic_bootstrap.py",
    "MODstore_deploy/modstore_server/db/autonomy_decisions.py",
    "MODstore_deploy/modstore_server/db/base.py",
    "MODstore_deploy/modstore_server/db/customer_value.py",
    "MODstore_deploy/modstore_server/db/ops_events.py",
    "MODstore_deploy/modstore_server/dead_letter_reconciler.py",
    "MODstore_deploy/modstore_server/duty_workforce_burnin.py",
    "MODstore_deploy/modstore_server/duty_workforce_contracts.py",
    "MODstore_deploy/modstore_server/duty_workforce_learning.py",
    "MODstore_deploy/modstore_server/employee_duty_input_resolver.py",
    "MODstore_deploy/modstore_server/employee_executor.py",
    "MODstore_deploy/modstore_server/employee_specialized_tools.py",
    "MODstore_deploy/modstore_server/employee_verification.py",
    "MODstore_deploy/modstore_server/eventing/global_bus.py",
    "MODstore_deploy/modstore_server/models.py",
    "MODstore_deploy/modstore_server/mod_employee_agent_runner.py",
    "MODstore_deploy/modstore_server/redline_approval_api.py",
    "MODstore_deploy/modstore_server/redline_approval_gate.py",
    "MODstore_deploy/modstore_server/runtime_provenance.py",
    "MODstore_deploy/modstore_server/self_evolution_knowledge.py",
    "MODstore_deploy/modstore_server/self_evolution_metrics_job.py",
    "MODstore_deploy/modstore_server/self_maintenance_deploy_receipts.py",
    "MODstore_deploy/modstore_server/self_maintenance_loop_runner.py",
    "MODstore_deploy/modstore_server/workflow_scheduler.py",
    "FHD/app/application/employee_runtime/risk_gate.py",
    "FHD/app/services/capability_proposal_recorder.py",
    "FHD/app/services/intent_confirmation_service.py",
    "FHD/config/duty_employee_work_contracts.json",
    "FHD/config/risk_actions.registry.json",
    "FHD/scripts/dev/capability_proposal_to_issue.py",
    "FHD/app/domain/autonomy/__init__.py",
    "FHD/app/domain/autonomy/approval_policy.py",
    "FHD/app/domain/autonomy/audit_log.py",
    "FHD/app/domain/autonomy/autonomy_guard.py",
    "FHD/app/domain/autonomy/operating_metrics.py",
    "FHD/app/domain/autonomy/risk_policy.py",
    "FHD/app/domain/autonomy/risk_types.py",
    "FHD/mods/_employees/host-checker/manifest.json",
    "FHD/mods/_employees/host-checker/backend/employees/host_checker.py",
    "FHD/mods/_employees/intent-analyst/manifest.json",
    "FHD/mods/_employees/intent-analyst/backend/employees/intent_analyst.py",
    "FHD/mods/_employees/market-frontend-dev/manifest.json",
    "FHD/mods/_employees/market-frontend-dev/backend/employees/market_frontend_dev.py",
    "FHD/mods/_employees/marketing-site-builder/manifest.json",
    "FHD/mods/_employees/marketing-site-builder/backend/employees/marketing_site_builder.py",
    "FHD/mods/_employees/seo-sitemap-curator/manifest.json",
    "FHD/mods/_employees/security-secrets-guard/manifest.json",
    "FHD/mods/_employees/security-secrets-guard/backend/employees/security_secrets_guard.py",
]
employee_root = Path(root) / "FHD" / "mods" / "_employees"
files.extend(
    str(path.relative_to(root))
    for pattern in ("*/manifest.json", "*/backend/employees/*.py")
    for path in employee_root.glob(pattern)
    if path.is_file()
)
files = sorted(set(files))
hashes = {}
for relative in files:
    path = os.path.join(root, relative)
    with open(path, "rb") as handle:
        hashes[relative] = hashlib.sha256(handle.read()).hexdigest()
artifact = hashlib.sha256(
    "\n".join(f"{key}:{hashes[key]}" for key in sorted(hashes)).encode()
).hexdigest()
payload = {
    "artifact_sha256": artifact,
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "files": hashes,
    "git_sha": git_sha,
    "runtime_root": root,
}
temporary = manifest + ".next"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temporary, manifest)
PY

python3 - "$ENV_FILE" "$TARGET_SHA" "$MANIFEST" "$TARGET_ROOT" <<'PY'
import os
import sys

path, git_sha, manifest, runtime_root = sys.argv[1:]
updates = {
    "MODSTORE_EXPECTED_GIT_SHA": git_sha,
    "MODSTORE_GIT_SHA": git_sha,
    "MODSTORE_RELEASE_MANIFEST": manifest,
    "XCAGI_FHD_RUNTIME_ROOT": os.path.join(runtime_root, "FHD"),
}
lines = []
if os.path.exists(path):
    lines = open(path, encoding="utf-8").read().splitlines()
kept = [line for line in lines if line.split("=", 1)[0] not in updates]
kept.extend(f"{key}={value}" for key, value in updates.items())
temporary = path + ".next"
with open(temporary, "w", encoding="utf-8") as handle:
    handle.write("\n".join(kept) + "\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY

for label in com.xcmax.modstore-daily com.xcmax.modstore-scheduler; do
  target="gui/$(id -u)/$label"
  if "$LAUNCHCTL_BIN" print "$target" >/dev/null 2>&1; then
    "$LAUNCHCTL_BIN" kickstart -k "$target"
  fi
done

READY=0
for _ in $(seq 1 "$HEALTH_ATTEMPTS"); do
  if "$CURL_BIN" --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8788/api/health >/dev/null \
      || "$CURL_BIN" --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8789/api/health >/dev/null; then
    READY=1
    break
  fi
  sleep "$HEALTH_SLEEP_SECONDS"
done
if [[ "$READY" != 1 ]]; then
  echo "[install] local runtime health failed" >&2
  rollback
  exit 5
fi

trap - ERR
echo "[install] exact local autonomy runtime installed git_sha=$TARGET_SHA manifest=$MANIFEST"
