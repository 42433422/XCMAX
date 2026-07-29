#!/usr/bin/env bash
# Para API 健康守护：先探活，再检查/修复 native ABI，最后按冷却窗口重启。
# 用法：bash para_health_watchdog.sh [--once]
set -u

PARA_API_URL="${PARA_API_URL:-http://127.0.0.1:3001}"
PARA_API_ROOT="${PARA_API_ROOT:-${HOME}/XCMAX-runtime/para-api/devfleet}"
PARA_NODE_BIN="${PARA_NODE_BIN:-${HOME}/.local/bin/node}"
PARA_NPM_BIN="${PARA_NPM_BIN:-${HOME}/.local/bin/npm}"
PARA_API_LABEL="${PARA_API_LABEL:-com.xcmax.para-api}"
PARA_WATCHDOG_INTERVAL_SEC="${PARA_WATCHDOG_INTERVAL_SEC:-15}"
PARA_RESTART_FAILURE_THRESHOLD="${PARA_RESTART_FAILURE_THRESHOLD:-3}"
PARA_RESTART_COOLDOWN_SEC="${PARA_RESTART_COOLDOWN_SEC:-120}"
PARA_REPAIR_COOLDOWN_SEC="${PARA_REPAIR_COOLDOWN_SEC:-900}"
PARA_HEALTH_WAIT_SEC="${PARA_HEALTH_WAIT_SEC:-45}"
PARA_DISK_CHECK_PATH="${PARA_DISK_CHECK_PATH:-${PARA_API_ROOT}}"
PARA_DISK_MIN_AVAILABLE_KB="${PARA_DISK_MIN_AVAILABLE_KB:-15728640}"
PARA_CLEANUP_COOLDOWN_SEC="${PARA_CLEANUP_COOLDOWN_SEC:-3600}"
PARA_CLEANUP_COMMAND="${PARA_CLEANUP_COMMAND:-${HOME}/Library/Application Support/XCMAX/run-para-cleanup.sh}"
PARA_WATCHDOG_STATE_DIR="${PARA_WATCHDOG_STATE_DIR:-${HOME}/Library/Application Support/XCMAX/para-watchdog}"
PARA_WATCHDOG_LOG_FILE="${PARA_WATCHDOG_LOG_FILE:-${HOME}/Library/Logs/XCMAX/para-health-watchdog.log}"
STATE_FILE="${PARA_WATCHDOG_STATE_DIR}/state.env"
LOCK_DIR="${PARA_WATCHDOG_STATE_DIR}/action.lock"
ONCE=0
[[ "${1:-}" == "--once" ]] && ONCE=1

mkdir -p "${PARA_WATCHDOG_STATE_DIR}" "$(dirname "${PARA_WATCHDOG_LOG_FILE}")"

log() {
  printf '[para-health] %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "${PARA_WATCHDOG_LOG_FILE}"
}

is_uint() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }

load_state() {
  failures=0
  last_cleanup_epoch=0
  last_repair_epoch=0
  last_restart_epoch=0
  if [[ -f "${STATE_FILE}" ]]; then
    # state.env 仅由本脚本写入三个整数，不接受任意键值。
    while IFS='=' read -r key value; do
      is_uint "${value}" || continue
      case "${key}" in
        failures) failures="${value}" ;;
        last_cleanup_epoch) last_cleanup_epoch="${value}" ;;
        last_repair_epoch) last_repair_epoch="${value}" ;;
        last_restart_epoch) last_restart_epoch="${value}" ;;
      esac
    done < "${STATE_FILE}"
  fi
}

save_state() {
  local tmp
  tmp="$(mktemp "${PARA_WATCHDOG_STATE_DIR}/state.XXXXXX")" || return 1
  printf 'failures=%s\nlast_cleanup_epoch=%s\nlast_repair_epoch=%s\nlast_restart_epoch=%s\n' \
    "${failures}" "${last_cleanup_epoch}" "${last_repair_epoch}" "${last_restart_epoch}" > "${tmp}"
  mv "${tmp}" "${STATE_FILE}"
}

healthy() {
  /usr/bin/curl --noproxy '*' -fsS --max-time 3 "${PARA_API_URL%/}/api/health" >/dev/null 2>&1
}

native_dependency_healthy() {
  [[ -x "${PARA_NODE_BIN}" && -d "${PARA_API_ROOT}" ]] || return 1
  (
    cd "${PARA_API_ROOT}" || exit 1
    "${PARA_NODE_BIN}" -e \
      "const Database=require('better-sqlite3');const db=new Database(':memory:');db.prepare('select 1').get();db.close()"
  ) >/dev/null 2>"${PARA_WATCHDOG_STATE_DIR}/native-check.err"
}

kickstart_api() {
  /bin/launchctl kickstart -k "gui/$(id -u)/${PARA_API_LABEL}" >> "${PARA_WATCHDOG_LOG_FILE}" 2>&1
}

wait_for_health() {
  local waited=0
  while (( waited < PARA_HEALTH_WAIT_SEC )); do
    healthy && return 0
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

acquire_action_lock() {
  if [[ -d "${LOCK_DIR}" ]]; then
    lock_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
    if ! is_uint "${lock_pid}" || ! kill -0 "${lock_pid}" 2>/dev/null; then
      rm -f "${LOCK_DIR}/pid" 2>/dev/null || true
      rmdir "${LOCK_DIR}" 2>/dev/null || true
    fi
  fi
  if mkdir "${LOCK_DIR}" 2>/dev/null; then
    printf '%s\n' "$$" > "${LOCK_DIR}/pid"
    return 0
  fi
  log "另一个修复动作正在执行，本轮跳过"
  return 1
}

release_action_lock() {
  rm -f "${LOCK_DIR}/pid" 2>/dev/null || true
  rmdir "${LOCK_DIR}" 2>/dev/null || true
}

available_disk_kb() {
  df -Pk "${PARA_DISK_CHECK_PATH}" 2>/dev/null | awk 'NR == 2 { print $4 }'
}

maybe_cleanup_disk() {
  local now="$1"
  local before_kb
  local after_kb
  is_uint "${PARA_DISK_MIN_AVAILABLE_KB}" || {
    log "PARA_DISK_MIN_AVAILABLE_KB 非法: ${PARA_DISK_MIN_AVAILABLE_KB}"
    return 1
  }
  is_uint "${PARA_CLEANUP_COOLDOWN_SEC}" || {
    log "PARA_CLEANUP_COOLDOWN_SEC 非法: ${PARA_CLEANUP_COOLDOWN_SEC}"
    return 1
  }
  before_kb="$(available_disk_kb)"
  is_uint "${before_kb}" || {
    log "无法读取磁盘剩余空间: ${PARA_DISK_CHECK_PATH}"
    return 1
  }
  (( before_kb < PARA_DISK_MIN_AVAILABLE_KB )) || return 0
  if (( now - last_cleanup_epoch < PARA_CLEANUP_COOLDOWN_SEC )); then
    return 0
  fi
  [[ -x "${PARA_CLEANUP_COMMAND}" ]] || {
    log "低磁盘水位但清理命令不可执行: available_kb=${before_kb} command=${PARA_CLEANUP_COMMAND}"
    return 1
  }
  acquire_action_lock || return 1
  last_cleanup_epoch="${now}"
  save_state
  log "低磁盘水位触发有界清理: available_kb=${before_kb} threshold_kb=${PARA_DISK_MIN_AVAILABLE_KB}"
  if ! "${PARA_CLEANUP_COMMAND}" --apply --reason low-disk >> "${PARA_WATCHDOG_LOG_FILE}" 2>&1; then
    log "有界清理失败；保留冷却避免反复占用磁盘"
    release_action_lock
    return 1
  fi
  after_kb="$(available_disk_kb)"
  log "有界清理完成: before_kb=${before_kb} after_kb=${after_kb:-unknown}"
  if is_uint "${after_kb}" && (( after_kb < PARA_DISK_MIN_AVAILABLE_KB )); then
    log "清理后仍低于安全水位；需处理 Para 范围外占用"
  fi
  release_action_lock
}

repair_native_dependency() {
  local now="$1"
  if (( now - last_repair_epoch < PARA_REPAIR_COOLDOWN_SEC )); then
    log "native 依赖仍不可用，修复冷却中（距上次 $((now - last_repair_epoch))s）"
    return 1
  fi
  acquire_action_lock || return 1
  last_repair_epoch="${now}"
  save_state
  log "检测到 better-sqlite3/Node ABI 不可加载，执行 npm rebuild better-sqlite3"
  if ! (
    cd "${PARA_API_ROOT}" || exit 1
    PATH="$(dirname "${PARA_NODE_BIN}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
      "${PARA_NPM_BIN}" rebuild better-sqlite3
  ) >> "${PARA_WATCHDOG_LOG_FILE}" 2>&1; then
    log "依赖重建失败；冷却期内不会反复重建或重启"
    release_action_lock
    return 1
  fi
  if ! native_dependency_healthy; then
    log "依赖重建完成但 native 自检仍失败；不重启故障进程"
    release_action_lock
    return 1
  fi
  log "native 依赖自检通过，启动 Para API"
  last_restart_epoch="${now}"
  save_state
  if ! kickstart_api; then
    release_action_lock
    return 1
  fi
  wait_for_health
  result=$?
  release_action_lock
  return "${result}"
}

check_once() {
  local now
  load_state
  now="$(date +%s)"
  maybe_cleanup_disk "${now}" || true
  if healthy; then
    if (( failures > 0 )); then
      log "健康恢复，连续失败计数由 ${failures} 清零"
    fi
    failures=0
    save_state
    return 0
  fi

  failures=$((failures + 1))
  save_state
  log "健康检查失败（连续 ${failures} 次）"

  if ! native_dependency_healthy; then
    if repair_native_dependency "${now}"; then
      failures=0
      save_state
      log "Para API 已在依赖修复后恢复"
      return 0
    fi
    return 1
  fi

  if (( failures < PARA_RESTART_FAILURE_THRESHOLD )); then
    return 1
  fi
  if (( now - last_restart_epoch < PARA_RESTART_COOLDOWN_SEC )); then
    log "API 仍不健康，重启冷却中（距上次 $((now - last_restart_epoch))s）"
    return 1
  fi
  acquire_action_lock || return 1
  last_restart_epoch="${now}"
  save_state
  log "native 自检正常但 API 连续不健康，执行一次受冷却保护的重启"
  if kickstart_api && wait_for_health; then
    failures=0
    save_state
    log "Para API 重启后恢复"
    release_action_lock
    return 0
  fi
  log "Para API 重启后仍不健康；等待冷却窗口，不连续重启"
  release_action_lock
  return 1
}

if (( ONCE == 1 )); then
  check_once
  exit $?
fi

log "watchdog 启动 interval=${PARA_WATCHDOG_INTERVAL_SEC}s repair_cooldown=${PARA_REPAIR_COOLDOWN_SEC}s restart_cooldown=${PARA_RESTART_COOLDOWN_SEC}s"
while true; do
  check_once || true
  sleep "${PARA_WATCHDOG_INTERVAL_SEC}"
done
