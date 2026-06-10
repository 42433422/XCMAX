#!/usr/bin/env bash
# 安装本机 MODstore 日更自启（macOS）
# - 项目在 Desktop/Documents 时：用「登录项」（GUI 会话，可访问 Desktop）
# - 其他路径：同时注册 launchd KeepAlive
# 用法：bash FHD/scripts/dev/install_modstore_daily_launchd.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
LABEL="com.xcmax.modstore-daily"
LOGIN_ITEM_NAME="XCMAX MODstore Daily"
PLIST_SRC="${SCRIPT_DIR}/com.xcmax.modstore-daily.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${FHD_ROOT}/logs"
RUN_SCRIPT="${SCRIPT_DIR}/run_modstore_daily_local.sh"
SUPPORT_DIR="${HOME}/Library/Application Support/XCMAX"
WRAPPER="${SUPPORT_DIR}/run-modstore-daily.sh"

log() { printf '[daily-autostart] %s\n' "$*"; }

[[ -f "${PLIST_SRC}" ]] || { log "缺少 ${PLIST_SRC}"; exit 1; }
[[ -x "${FHD_ROOT}/.venv/bin/python" ]] || { log "缺少 FHD venv"; exit 1; }

mkdir -p "${LOG_DIR}" "${SUPPORT_DIR}" "${HOME}/Library/LaunchAgents"
cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
# 由 install_modstore_daily_launchd.sh 生成 — 勿手改
export MODSTORE_DAILY_FOREGROUND=1
exec /bin/bash "${RUN_SCRIPT}"
EOF
chmod +x "${WRAPPER}"

_on_desktop_or_documents() {
  case "${XCMAX_ROOT}" in
    "${HOME}/Desktop"/*|"${HOME}/Documents"/*) return 0 ;;
    *) return 1 ;;
  esac
}

_install_login_item() {
  /usr/bin/osascript <<APPLESCRIPT
tell application "System Events"
  set itemPath to POSIX file "${WRAPPER}"
  set existing to name of every login item
  if existing does not contain "${LOGIN_ITEM_NAME}" then
    make login item at end with properties {path:itemPath, name:"${LOGIN_ITEM_NAME}", hidden:true}
  end if
end tell
APPLESCRIPT
  log "已注册登录项「${LOGIN_ITEM_NAME}」→ ${WRAPPER}"
}

_install_launchd() {
  sed \
    -e "s|__XCMAX_RUN_MODSTORE_DAILY__|${WRAPPER}|g" \
    -e "s|__XCMAX_LOG_DIR__|${LOG_DIR}|g" \
    -e "s|__XCMAX_ROOT__|${HOME}|g" \
    "${PLIST_SRC}" > "${PLIST_DST}"
  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID_NUM}" "${PLIST_DST}"
  launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  log "已注册 launchd ${PLIST_DST}"
}

_remove_launchd() {
  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  rm -f "${PLIST_DST}"
}

if _on_desktop_or_documents; then
  log "项目在 Desktop/Documents — 使用登录项自启（launchd 无权限读 Desktop 脚本）"
  _remove_launchd
  _install_login_item
else
  _install_launchd
  _install_login_item
fi

# 若当前无调度器实例，立即拉起
sched="false"
if curl -sf "http://127.0.0.1:8788/api/health" >/dev/null 2>&1; then
  sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo 'false')"
fi
if [[ "${sched}" != "True" && "${sched}" != "true" ]]; then
  log "当前无日更调度器 — 立即启动…"
  MODSTORE_DAILY_FORCE_RESTART=1 bash "${RUN_SCRIPT}"
  sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo '?')"
fi

log "MODstore :8788 scheduler_running=${sched}"
log "08:00 自动 digest：全开 FHD/Vite/模拟器 → 跑完自动关（MODSTORE_SURFACE_AUDIT_STOP_AFTER=1）"
log "日志: ${LOG_DIR}/modstore-daily.launchd.{log,err.log}  ·  .xcmax-logs/surface-audit-*.log"
log "手动触发: bash FHD/scripts/dev/trigger_digest_now_local.sh"
log "一键验证: bash FHD/scripts/dev/run_digest_full_stack.sh"
