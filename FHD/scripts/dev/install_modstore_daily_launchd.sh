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
RUNNER_COPY="${SUPPORT_DIR}/run_modstore_daily_local.sh"
COMMAND_FILE="${SUPPORT_DIR}/run-modstore-daily.command"
ENV_SNAPSHOT="${SUPPORT_DIR}/modstore-daily.env"
LAUNCHER_OSA="${SUPPORT_DIR}/launch-modstore-daily.applescript"
LOGIN_APP="${SUPPORT_DIR}/${LOGIN_ITEM_NAME}.app"

log() { printf '[daily-autostart] %s\n' "$*"; }

[[ -f "${PLIST_SRC}" ]] || { log "缺少 ${PLIST_SRC}"; exit 1; }
[[ -x "${FHD_ROOT}/.venv/bin/python" ]] || { log "缺少 FHD venv"; exit 1; }

mkdir -p "${LOG_DIR}" "${SUPPORT_DIR}" "${HOME}/Library/LaunchAgents"
cp "${RUN_SCRIPT}" "${RUNNER_COPY}"
chmod +x "${RUNNER_COPY}"
MODSTORE_DEPLOY_ROOT="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy"
if [[ ! -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]]; then
  MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
fi
: > "${ENV_SNAPSHOT}"
for f in \
  "${MODSTORE_DEPLOY_ROOT}/.env" \
  "${MODSTORE_DEPLOY_ROOT}/.env.production" \
  "${MODSTORE_DEPLOY_ROOT}/.env.production.synced" \
  "${MODSTORE_DEPLOY_ROOT}/.env.daily-closure" \
  "${MODSTORE_DEPLOY_ROOT}/.env.local" \
  "${MODSTORE_DEPLOY_ROOT}/.env.smtp.local" \
  "${FHD_ROOT}/XCAGI/.env.smtp.local" \
  "${FHD_ROOT}/XCAGI/.env.cursor.local"
do
  if [[ -f "${f}" ]]; then
    cat "${f}" >> "${ENV_SNAPSHOT}"
    printf '\n' >> "${ENV_SNAPSHOT}"
  fi
done
cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
# 由 install_modstore_daily_launchd.sh 生成 — 勿手改
export MODSTORE_DAILY_FOREGROUND=1
export MODSTORE_DAILY_FHD_ROOT="${FHD_ROOT}"
export MODSTORE_DAILY_XCMAX_ROOT="${XCMAX_ROOT}"
export MODSTORE_DAILY_SCRIPT_DIR_OVERRIDE="${SCRIPT_DIR}"
export MODSTORE_DAILY_ENV_SNAPSHOT="${ENV_SNAPSHOT}"
export MODSTORE_DAILY_SKIP_ENV_FILES=1
exec /bin/bash "${RUNNER_COPY}"
EOF
chmod +x "${WRAPPER}"
cat > "${COMMAND_FILE}" <<EOF
#!/bin/bash
exec /bin/bash "${RUN_SCRIPT}"
EOF
chmod +x "${COMMAND_FILE}"
cat > "${LAUNCHER_OSA}" <<EOF
tell application "Terminal"
  activate
  do script "export MODSTORE_DAILY_FOREGROUND=1; /bin/bash " & quoted form of "${RUN_SCRIPT}"
  delay 1
  try
    set miniaturized of front window to true
  end try
end tell
EOF

_build_login_item_app() {
  /usr/bin/osacompile -o "${LOGIN_APP}" "${LAUNCHER_OSA}" >/dev/null
}

_on_desktop_or_documents() {
  case "${XCMAX_ROOT}" in
    "${HOME}/Desktop"/*|"${HOME}/Documents"/*) return 0 ;;
    *) return 1 ;;
  esac
}

_install_login_item() {
  _build_login_item_app
  /usr/bin/osascript <<APPLESCRIPT
tell application "System Events"
  set itemPath to POSIX file "${LOGIN_APP}"
  set matched to false
  repeat with li in every login item
    if name of li is "${LOGIN_ITEM_NAME}" then
      set path of li to itemPath
      set hidden of li to true
      set matched to true
      exit repeat
    end if
  end repeat
  if matched is false then
    make login item at end with properties {path:itemPath, name:"${LOGIN_ITEM_NAME}", hidden:true}
  end if
end tell
APPLESCRIPT
  log "已注册登录项「${LOGIN_ITEM_NAME}」→ ${LOGIN_APP}"
}

_install_launchd() {
  if _on_desktop_or_documents; then
    cat > "${PLIST_DST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>Terminal</string>
    <string>${COMMAND_FILE}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/modstore-daily.launchd.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/modstore-daily.launchd.err.log</string>
  <key>WorkingDirectory</key>
  <string>${HOME}</string>
</dict>
</plist>
EOF
  else
    sed \
      -e "s|__XCMAX_RUN_MODSTORE_DAILY__|${WRAPPER}|g" \
      -e "s|__XCMAX_LOG_DIR__|${LOG_DIR}|g" \
      -e "s|__XCMAX_ROOT__|${HOME}|g" \
      "${PLIST_SRC}" > "${PLIST_DST}"
  fi
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
  log "项目在 Desktop/Documents — 使用 Library Support env 快照 + launchd 后台自启"
else
  log "使用 launchd 自启"
fi
_install_launchd

# 若当前无调度器实例，立即拉起
sched="false"
if curl -sf "http://127.0.0.1:8788/api/health" >/dev/null 2>&1; then
  sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo 'false')"
fi
if [[ "${sched}" != "True" && "${sched}" != "true" ]]; then
  log "当前无日更调度器 — 立即启动…"
  UID_NUM="$(id -u)"
  launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || launchctl bootstrap "gui/${UID_NUM}" "${PLIST_DST}" 2>/dev/null || true
  sleep 3
  sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo '?')"
fi

log "MODstore :8788 scheduler_running=${sched}"
log "08:00 自动 digest：全开 FHD/Vite/模拟器 → 跑完自动关（MODSTORE_SURFACE_AUDIT_STOP_AFTER=1）"
log "日志: ${LOG_DIR}/modstore-daily.launchd.{log,err.log}  ·  .xcmax-logs/surface-audit-*.log"
log "手动触发: bash FHD/scripts/dev/trigger_digest_now_local.sh"
log "一键验证: bash FHD/scripts/dev/run_digest_full_stack.sh"
