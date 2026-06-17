#!/usr/bin/env bash
# 安装本机 MODstore 日更自启（macOS）
# - 将 MODstore 运行时镜像同步到非受保护目录 ~/XCMAX-runtime/modstore-daily
# - launchd 直接执行 Library Support wrapper，不再依赖 Desktop 路径/GUI 登录项
# 用法：bash FHD/scripts/dev/install_modstore_daily_launchd.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
LABEL="com.xcmax.modstore-daily"
LOGIN_ITEM_NAME="XCMAX MODstore Daily"
PLIST_SRC="${SCRIPT_DIR}/com.xcmax.modstore-daily.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/XCMAX"
RUN_SCRIPT="${SCRIPT_DIR}/run_modstore_daily_local.sh"
SUPPORT_DIR="${HOME}/Library/Application Support/XCMAX"
WRAPPER="${SUPPORT_DIR}/run-modstore-daily.sh"
RUNNER_COPY="${SUPPORT_DIR}/run_modstore_daily_local.sh"
COMMAND_FILE="${SUPPORT_DIR}/run-modstore-daily.command"
ENV_SNAPSHOT="${SUPPORT_DIR}/modstore-daily.env"
LAUNCHER_OSA="${SUPPORT_DIR}/launch-modstore-daily.applescript"
LOGIN_APP="${SUPPORT_DIR}/${LOGIN_ITEM_NAME}.app"
RUNTIME_ROOT="${HOME}/XCMAX-runtime/modstore-daily"
RUNTIME_DEPLOY_ROOT="${RUNTIME_ROOT}/MODstore_deploy"
RUNTIME_PACKAGES_ROOT="${RUNTIME_ROOT}/packages"
STATE_ROOT="${SUPPORT_DIR}/modstore-daily"
RUNTIME_DB_PATH="${STATE_ROOT}/modstore.db"
RUNTIME_VAR_ROOT="${STATE_ROOT}/runtime"
RUNTIME_EVENT_OUTBOX_PATH="${STATE_ROOT}/event_outbox.jsonl"
RUNTIME_WEBHOOK_EVENTS_DIR="${STATE_ROOT}/webhook_events"

log() { printf '[daily-autostart] %s\n' "$*"; }

[[ -f "${PLIST_SRC}" ]] || { log "缺少 ${PLIST_SRC}"; exit 1; }
[[ -x "${FHD_ROOT}/.venv/bin/python" ]] || { log "缺少 FHD venv"; exit 1; }

mkdir -p "${LOG_DIR}" "${SUPPORT_DIR}" "${HOME}/Library/LaunchAgents" "${STATE_ROOT}" "${RUNTIME_VAR_ROOT}" "${RUNTIME_WEBHOOK_EVENTS_DIR}"
cp "${RUN_SCRIPT}" "${RUNNER_COPY}"
chmod +x "${RUNNER_COPY}"
MODSTORE_DEPLOY_ROOT="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy"
if [[ ! -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]]; then
  MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
fi
mkdir -p "${RUNTIME_ROOT}"
log "同步运行时镜像 → ${RUNTIME_DEPLOY_ROOT}"
rsync -a --delete "${MODSTORE_DEPLOY_ROOT}/" "${RUNTIME_DEPLOY_ROOT}/"
log "同步共享 packages → ${RUNTIME_PACKAGES_ROOT}"
mkdir -p "${RUNTIME_PACKAGES_ROOT}"
rsync -a --delete "${XCMAX_ROOT}/packages/" "${RUNTIME_PACKAGES_ROOT}/"
if [[ ! -f "${RUNTIME_DB_PATH}" ]]; then
  if [[ -f "${MODSTORE_DEPLOY_ROOT}/modstore_server/modstore.db" ]]; then
    cp "${MODSTORE_DEPLOY_ROOT}/modstore_server/modstore.db" "${RUNTIME_DB_PATH}"
  elif [[ -f "${RUNTIME_DEPLOY_ROOT}/modstore_server/modstore.db" ]]; then
    cp "${RUNTIME_DEPLOY_ROOT}/modstore_server/modstore.db" "${RUNTIME_DB_PATH}"
  fi
fi
chmod 600 "${RUNTIME_DB_PATH}" 2>/dev/null || true
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
    tr -d '\r' < "${f}" >> "${ENV_SNAPSHOT}"
    printf '\n' >> "${ENV_SNAPSHOT}"
  fi
done
cat >> "${ENV_SNAPSHOT}" <<EOF
MODSTORE_RUNTIME_STATE_ROOT=${STATE_ROOT}
MODSTORE_RUNTIME_DB_PATH=${RUNTIME_DB_PATH}
MODSTORE_RUNTIME_DIR=${RUNTIME_VAR_ROOT}
MODSTORE_EVENT_OUTBOX_PATH=${RUNTIME_EVENT_OUTBOX_PATH}
MODSTORE_WEBHOOK_EVENTS_DIR=${RUNTIME_WEBHOOK_EVENTS_DIR}
MODSTORE_DEPLOY_ROOT=${RUNTIME_DEPLOY_ROOT}
MODSTORE_REPO_ROOT=${RUNTIME_DEPLOY_ROOT}
MODSTORE_DB_PATH=${RUNTIME_DB_PATH}
DATABASE_URL=sqlite:////${RUNTIME_DB_PATH#/}
EOF
cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
# 由 install_modstore_daily_launchd.sh 生成 — 勿手改
if [[ "\${MODSTORE_DAILY_ENV_CLEANROOM:-0}" != "1" ]]; then
  exec /usr/bin/env -i \
    HOME="${HOME}" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    MODSTORE_DAILY_ENV_CLEANROOM=1 \
    /bin/bash "\$0"
fi
export MODSTORE_DAILY_FOREGROUND=1
export MODSTORE_DAILY_FHD_ROOT="${FHD_ROOT}"
export MODSTORE_DAILY_XCMAX_ROOT="${XCMAX_ROOT}"
export MODSTORE_DAILY_SCRIPT_DIR_OVERRIDE="${SCRIPT_DIR}"
export MODSTORE_DAILY_ENV_SNAPSHOT="${ENV_SNAPSHOT}"
export MODSTORE_DAILY_SKIP_ENV_FILES=1
export MODSTORE_RUNTIME_ROOT="${RUNTIME_ROOT}"
export MODSTORE_RUNTIME_STATE_ROOT="${STATE_ROOT}"
export MODSTORE_RUNTIME_DB_PATH="${RUNTIME_DB_PATH}"
export MODSTORE_RUNTIME_DIR="${RUNTIME_VAR_ROOT}"
export MODSTORE_EVENT_OUTBOX_PATH="${RUNTIME_EVENT_OUTBOX_PATH}"
export MODSTORE_WEBHOOK_EVENTS_DIR="${RUNTIME_WEBHOOK_EVENTS_DIR}"
export MODSTORE_DEPLOY_ROOT="${RUNTIME_DEPLOY_ROOT}"
export MODSTORE_REPO_ROOT="${RUNTIME_DEPLOY_ROOT}"
export MODSTORE_DB_PATH="${RUNTIME_DB_PATH}"
export DATABASE_URL="sqlite:////${RUNTIME_DB_PATH#/}"
export PYTHONPATH="${RUNTIME_DEPLOY_ROOT}:${RUNTIME_PACKAGES_ROOT}/xcagi_common"
export MODSTORE_DAILY_DAEMON_LOG_DIR="${LOG_DIR}"
exec /bin/bash "${RUNNER_COPY}"
EOF
chmod +x "${WRAPPER}"
cat > "${COMMAND_FILE}" <<EOF
#!/bin/bash
exec /bin/bash "${WRAPPER}"
EOF
chmod +x "${COMMAND_FILE}"
cat > "${LAUNCHER_OSA}" <<EOF
tell application "Terminal"
  activate
  do script "/bin/bash " & quoted form of "${WRAPPER}"
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
  sed \
    -e "s|__XCMAX_RUN_MODSTORE_DAILY__|${WRAPPER}|g" \
    -e "s|__XCMAX_LOG_DIR__|${LOG_DIR}|g" \
    -e "s|__XCMAX_ROOT__|${HOME}|g" \
    "${PLIST_SRC}" > "${PLIST_DST}"
  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if ! launchctl bootstrap "gui/${UID_NUM}" "${PLIST_DST}"; then
    sleep 2
    launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
    sleep 1
    launchctl bootstrap "gui/${UID_NUM}" "${PLIST_DST}"
  fi
  launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  log "已注册 launchd ${PLIST_DST}"
}

_remove_launchd() {
  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  rm -f "${PLIST_DST}"
}

if _on_desktop_or_documents; then
  log "项目在 Desktop/Documents — 运行时已迁出到 ${RUNTIME_ROOT}"
else
  log "使用 launchd 自启"
fi
_install_launchd

# 若当前无调度器实例，立即拉起
sched="false"
for _ in $(seq 1 75); do
  if curl -sf "http://127.0.0.1:8788/api/health" >/dev/null 2>&1; then
    sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo 'false')"
    if [[ "${sched}" == "True" || "${sched}" == "true" ]]; then
      break
    fi
  fi
  sleep 1
done
if [[ "${sched}" != "True" && "${sched}" != "true" ]]; then
  log "当前无日更调度器 — 重启 launchd job…"
  UID_NUM="$(id -u)"
  launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  for _ in $(seq 1 75); do
    if curl -sf "http://127.0.0.1:8788/api/health" >/dev/null 2>&1; then
      sched="$("${FHD_ROOT}/.venv/bin/python" -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/health')).get('scheduler_running'))" 2>/dev/null || echo '?')"
      if [[ "${sched}" == "True" || "${sched}" == "true" ]]; then
        break
      fi
    fi
    sleep 1
  done
fi

log "MODstore :8788 scheduler_running=${sched}"
log "状态目录: ${STATE_ROOT}"
log "08:00 自动 digest：全开 FHD/Vite/模拟器 → 跑完自动关（MODSTORE_SURFACE_AUDIT_STOP_AFTER=1）"
log "日志: ${LOG_DIR}/modstore-daily.launchd.{log,err.log}"
log "手动触发: bash FHD/scripts/dev/trigger_digest_now_local.sh"
log "一键验证: bash FHD/scripts/dev/run_digest_full_stack.sh"
