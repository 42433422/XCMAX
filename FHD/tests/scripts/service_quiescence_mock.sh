#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$SCRIPT_DIR/FHD/scripts/deploy/lib/service_quiescence.sh"
source "$SCRIPT_DIR/FHD/scripts/deploy/lib/apply_recovery.sh"
STATE="$(mktemp -d)"
trap 'rm -rf -- "$STATE"' EXIT
printf 'active\n' > "$STATE/unit"
printf 'before\n' > "$STATE/customer-data"
GATE_LOG="$STATE/gates"
: > "$GATE_LOG"

systemctl() {
  case "$1" in
    show) [[ "${MOCK_QUERY_FAIL:-0}" != 1 ]] && cat "$STATE/unit" ;;
    is-active) [[ "$(cat "$STATE/unit")" == "active" ]] ;;
    stop) [[ "${MOCK_REFUSE_STOP:-0}" == 1 ]] || printf 'inactive\n' > "$STATE/unit" ;;
    start) printf 'active\n' > "$STATE/unit" ;;
    *) return 90 ;;
  esac
}
autonomy_evaluate_action() {
  printf '%s %s\n' "$1" "$2" >> "$GATE_LOG"
  [[ "${MOCK_REJECT_GATE:-0}" != 1 ]]
}

fhd_stop_service_for_release fhd-full.service restart:release:test
! systemctl is-active --quiet fhd-full.service
# Writes only occur in the deployment window after the mock confirms no writer.
printf 'latest-after-copy-window\n' > "$STATE/customer-data"
fhd_restore_service_after_failed_apply fhd-full.service restart:release:test
systemctl is-active --quiet fhd-full.service
[[ "$(cat "$STATE/customer-data")" == "latest-after-copy-window" ]]
[[ "$(wc -l < "$GATE_LOG" | tr -d ' ')" == 2 ]]
[[ "$(awk '{print $2}' "$GATE_LOG" | sort -u | wc -l | tr -d ' ')" == 1 ]]

# A stop command that returns success but leaves the service active is rejected.
printf 'active\n' > "$STATE/unit"
MOCK_REFUSE_STOP=1
if fhd_stop_service_for_release fhd-full.service restart:release:stuck 2>/dev/null; then
  echo 'stop refusal was not detected' >&2
  exit 1
fi
systemctl is-active --quiet fhd-full.service

# A denied existing restart_service gate prevents the stop and apply window.
MOCK_REFUSE_STOP=0
MOCK_REJECT_GATE=1
if fhd_stop_service_for_release fhd-full.service restart:release:denied; then
  echo 'denied restart gate was ignored' >&2
  exit 1
fi
systemctl is-active --quiet fhd-full.service
MOCK_REJECT_GATE=0
MOCK_QUERY_FAIL=1
if fhd_stop_service_for_release fhd-full.service restart:release:unknown; then
  echo 'unavailable service state was treated as inactive' >&2
  exit 1
fi
systemctl is-active --quiet fhd-full.service
[[ "$FHD_SERVICE_STOP_ATTEMPTED" == 0 ]]
MOCK_QUERY_FAIL=0
echo 'service quiescence mock passed'
rollback_from_backup_mock() { return 1; } # model receipt/data validation refusal

# A receipt/data guard can reject rollback. The workspace survives cleanup only
# after a protected copy has been verified; failed copies leave the source intact.
OLD_TMP="$STATE/old-cleanup-tmp"
mkdir -p "$OLD_TMP/mods-update-state/prior/bundled" "$OLD_TMP/scripts/deploy/lib"
printf 'rollback plan\n' > "$OLD_TMP/mods-update-state/plan.json"
printf 'only prior snapshot\n' > "$OLD_TMP/mods-update-state/prior/bundled/logic.py"
printf 'only rollback helper\n' > "$OLD_TMP/scripts/deploy/lib/mod_tree_guard.py"
if rollback_from_backup_mock; then
  echo 'mock rollback should have been blocked' >&2
  exit 1
fi
rm -rf -- "$OLD_TMP" # reproduce the former unconditional cleanup after return 1
[[ ! -e "$OLD_TMP/mods-update-state/plan.json" ]]
echo 'reproduced: failed rollback followed by unconditional cleanup deleted recovery material'

printf 'active\n' > "$STATE/unit"
MOCK_REJECT_GATE=0
fhd_stop_service_for_release fhd-full.service restart:release:recovery
APPLY_TMP="$STATE/apply-tmp"
BACKUP="$STATE/backups/pre-test"
mkdir -p "$APPLY_TMP/mods-update-state/prior/bundled" "$APPLY_TMP/scripts/deploy/lib" "$BACKUP"
printf '{"bundled":{"prior_hash":"abc"}}\n' > "$APPLY_TMP/mods-update-state/plan.json"
printf 'prior-code\n' > "$APPLY_TMP/mods-update-state/prior/bundled/logic.py"
printf 'rollback-helper\n' > "$APPLY_TMP/scripts/deploy/lib/mod_tree_guard.py"
RECOVERY_REQUIRED=0
if rollback_from_backup_mock; then
  echo 'mock rollback should have been blocked' >&2
  exit 1
else
  RECOVERY_REQUIRED=1
fi
[[ "$RECOVERY_REQUIRED" == 1 ]]
fhd_restore_service_after_failed_apply fhd-full.service restart:release:recovery
systemctl is-active --quiet fhd-full.service
fhd_preserve_recovery_material "$APPLY_TMP" "$BACKUP" test
RECOVERY="$BACKUP/recovery-test"
[[ -f "$RECOVERY/mods-update-state/plan.json" ]]
[[ "$(cat "$RECOVERY/mods-update-state/prior/bundled/logic.py")" == prior-code ]]
[[ "$(cat "$RECOVERY/scripts/deploy/lib/mod_tree_guard.py")" == rollback-helper ]]
rm -rf -- "$APPLY_TMP"
[[ -f "$RECOVERY/mods-update-state/plan.json" ]]

APPLY_TMP="$STATE/apply-tmp-copy-failure"
mkdir -p "$APPLY_TMP/mods-update-state" "$BACKUP"
printf 'recovery plan\n' > "$APPLY_TMP/mods-update-state/plan.json"
cp() { return 1; }
if fhd_preserve_recovery_material "$APPLY_TMP" "$BACKUP" copy-failure 2>/dev/null; then
  unset -f cp
  echo 'mock recovery copy should have failed' >&2
  exit 1
fi
unset -f cp
[[ -f "$APPLY_TMP/mods-update-state/plan.json" ]]
echo 'failed recovery-copy retention mock passed'
