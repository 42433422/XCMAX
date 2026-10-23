# shellcheck shell=bash
# Service isolation for one release apply, using the existing restart_service gate.

fhd_stop_service_for_release() {
  local service="${1:?service is required}"
  local action_id="${2:?release action id is required}"
  local state pid original_pid started elapsed interrupted=0
  FHD_SERVICE_WAS_ACTIVE=0
  FHD_SERVICE_STOP_ATTEMPTED=0
  FHD_SERVICE_QUIESCED=0

  autonomy_evaluate_action "restart_service" "$action_id" || return $?
  state="$(systemctl show --property=ActiveState --value "$service")" || return $?
  original_pid="$(systemctl show --property=MainPID --value "$service")" || return $?
  [[ "$original_pid" =~ ^[0-9]+$ ]] || return 1
  case "$state" in
    inactive) [[ "$original_pid" == 0 ]] || return 1; FHD_SERVICE_QUIESCED=1; return 0 ;;
    active|activating|reloading|deactivating|failed) FHD_SERVICE_WAS_ACTIVE=1 ;;
    *) echo "[deploy] ERROR: cannot establish service state: $service" >&2; return 1 ;;
  esac

  FHD_SERVICE_STOP_ATTEMPTED=1
  started=$SECONDS
  systemctl stop --no-block "$service" || return $?
  while true; do
    state="$(systemctl show --property=ActiveState --value "$service")" || return $?
    pid="$(systemctl show --property=MainPID --value "$service")" || return $?
    elapsed=$((SECONDS - started))
    if [[ "$state" == inactive && "$pid" == 0 ]]; then
      FHD_SERVICE_QUIESCED=1
      return 0
    fi
    if [[ ! "$pid" =~ ^[0-9]+$ || "$state" == failed || ( "$pid" != 0 && "$pid" != "$original_pid" ) || "$elapsed" -ge 85 \
      || ( "$state" == active && "$elapsed" -ge 5 ) ]]; then
      echo "[deploy] ERROR: service did not quiesce: $service state=$state pid=$pid" >&2
      return 1
    fi
    # Older Uvicorn releases wait forever for live streams. Interrupt only the
    # original unit's main process; a real inactive state is still mandatory.
    if [[ "$state" == deactivating && "$elapsed" -ge 60 && "$interrupted" == 0 && "$pid" != 0 ]]; then
      systemctl kill --kill-who=main --signal=SIGINT "$service" || return $?
      interrupted=1
    fi
    sleep 1
  done
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
