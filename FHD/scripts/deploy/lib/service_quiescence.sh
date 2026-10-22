# shellcheck shell=bash
# Service isolation for one release apply, using the existing restart_service gate.

fhd_stop_service_for_release() {
  local service="${1:?service is required}"
  local action_id="${2:?release action id is required}"
  local state
  FHD_SERVICE_WAS_ACTIVE=0
  FHD_SERVICE_STOP_ATTEMPTED=0
  FHD_SERVICE_QUIESCED=0

  autonomy_evaluate_action "restart_service" "$action_id" || return $?
  state="$(systemctl show --property=ActiveState --value "$service")" || return $?
  case "$state" in
    inactive) return 0 ;;
    active|activating|reloading|deactivating|failed) FHD_SERVICE_WAS_ACTIVE=1 ;;
    *) echo "[deploy] ERROR: cannot establish service state: $service" >&2; return 1 ;;
  esac

  FHD_SERVICE_STOP_ATTEMPTED=1
  systemctl stop "$service" || return $?
  state="$(systemctl show --property=ActiveState --value "$service")" || return $?
  if [[ "$state" != "inactive" ]]; then
    echo "[deploy] ERROR: service remained active after stop: $service" >&2
    return 1
  fi
  FHD_SERVICE_QUIESCED=1
}

fhd_restore_service_after_failed_apply() {
  local service="${1:?service is required}"
  local action_id="${2:?release action id is required}"
  if [[ "${FHD_SERVICE_STOP_ATTEMPTED:-0}" != "1" || "${FHD_SERVICE_WAS_ACTIVE:-0}" != "1" ]]; then
    return 0
  fi
  if systemctl is-active --quiet "$service"; then
    FHD_SERVICE_QUIESCED=0
    return 0
  fi
  autonomy_evaluate_action "restart_service" "$action_id" || return $?
  systemctl start "$service" || return $?
  systemctl is-active --quiet "$service" || {
    echo "[deploy] ERROR: service did not become active during recovery: $service" >&2
    return 1
  }
  FHD_SERVICE_QUIESCED=0
}
