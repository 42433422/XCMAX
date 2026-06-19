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
ANDROID_START_COPY="${SUPPORT_DIR}/start_android_emulator.sh"
COMMAND_FILE="${SUPPORT_DIR}/run-modstore-daily.command"
ENV_SNAPSHOT="${SUPPORT_DIR}/modstore-daily.env"
LAUNCHER_OSA="${SUPPORT_DIR}/launch-modstore-daily.applescript"
LOGIN_APP="${SUPPORT_DIR}/${LOGIN_ITEM_NAME}.app"
RUNTIME_ROOT="${HOME}/XCMAX-runtime/modstore-daily"
RUNTIME_DEPLOY_ROOT="${RUNTIME_ROOT}/MODstore_deploy"
RUNTIME_PACKAGES_ROOT="${RUNTIME_ROOT}/packages"
RUNTIME_FHD_ROOT="${RUNTIME_ROOT}/FHD"
RUNTIME_FHD_CONFIG_ROOT="${RUNTIME_FHD_ROOT}/config"
RUNTIME_GIT_MIRROR="${RUNTIME_ROOT}/XCMAX.git"
RUNTIME_ANDROID_SDK_ROOT="${SUPPORT_DIR}/android-sdk"
STATE_ROOT="${SUPPORT_DIR}/modstore-daily"
RUNTIME_DB_PATH="${STATE_ROOT}/modstore.db"
RUNTIME_VAR_ROOT="${STATE_ROOT}/runtime"
RUNTIME_EVENT_OUTBOX_PATH="${STATE_ROOT}/event_outbox.jsonl"
RUNTIME_WEBHOOK_EVENTS_DIR="${STATE_ROOT}/webhook_events"
SURFACE_AUDIT_STATE_ROOT="${STATE_ROOT}/surface_audit"
POST_DEPLOY_SMOKE_STATE_FILE="${STATE_ROOT}/post-deploy-smoke-last.json"

log() { printf '[daily-autostart] %s\n' "$*"; }

_env_snapshot_quote() {
  local v="${1-}"
  v="${v//\'/\'\\\'\'}"
  printf "'%s'" "${v}"
}

_env_snapshot_put() {
  local k="$1" v="${2-}"
  [[ "${k}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
  printf '%s=' "${k}" >> "${ENV_SNAPSHOT}"
  _env_snapshot_quote "${v}" >> "${ENV_SNAPSHOT}"
  printf '\n' >> "${ENV_SNAPSHOT}"
}

_env_snapshot_append_file() {
  local f="$1" line k v
  [[ -f "${f}" ]] || return 0
  printf '# from %s\n' "${f}" >> "${ENV_SNAPSHOT}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line//$'\r'/}"
    line="$(printf '%s' "${line}" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//;s/^export[[:space:]]+//')"
    [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue
    k="${line%%=*}"
    v="${line#*=}"
    k="$(printf '%s' "${k}" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"
    v="$(printf '%s' "${v}" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"
    case "${v}" in
      \"*\") v="${v#\"}"; v="${v%\"}" ;;
      \'*\') v="${v#\'}"; v="${v%\'}" ;;
    esac
    _env_snapshot_put "${k}" "${v}"
  done < "${f}"
  printf '\n' >> "${ENV_SNAPSHOT}"
}

[[ -f "${PLIST_SRC}" ]] || { log "缺少 ${PLIST_SRC}"; exit 1; }
[[ -x "${FHD_ROOT}/.venv/bin/python" ]] || { log "缺少 FHD venv"; exit 1; }

mkdir -p "${LOG_DIR}" "${SUPPORT_DIR}" "${HOME}/Library/LaunchAgents" "${STATE_ROOT}" "${RUNTIME_VAR_ROOT}" "${RUNTIME_WEBHOOK_EVENTS_DIR}" "${SURFACE_AUDIT_STATE_ROOT}"
cp "${RUN_SCRIPT}" "${RUNNER_COPY}"
chmod +x "${RUNNER_COPY}"
cp "${SCRIPT_DIR}/start_android_emulator.sh" "${ANDROID_START_COPY}"
chmod +x "${ANDROID_START_COPY}"
MODSTORE_DEPLOY_ROOT="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy"
if [[ ! -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]]; then
  MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
fi
mkdir -p "${RUNTIME_ROOT}"
log "同步运行时镜像 → ${RUNTIME_DEPLOY_ROOT}"
rsync -a --delete \
  --exclude "market/coverage-current/" \
  --exclude "market/coverage-current/.tmp/" \
  --exclude ".pytest_cache/" \
  --exclude "__pycache__/" \
  "${MODSTORE_DEPLOY_ROOT}/" "${RUNTIME_DEPLOY_ROOT}/"
log "同步共享 packages → ${RUNTIME_PACKAGES_ROOT}"
mkdir -p "${RUNTIME_PACKAGES_ROOT}"
rsync -a --delete "${XCMAX_ROOT}/packages/" "${RUNTIME_PACKAGES_ROOT}/"
if command -v git >/dev/null 2>&1; then
  if [[ -d "${RUNTIME_GIT_MIRROR}/objects" ]]; then
    log "同步 git mirror → ${RUNTIME_GIT_MIRROR}"
    git --git-dir="${RUNTIME_GIT_MIRROR}" fetch --prune "${XCMAX_ROOT}" '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' >/dev/null 2>&1 || true
  else
    log "创建 git mirror → ${RUNTIME_GIT_MIRROR}"
    rm -rf "${RUNTIME_GIT_MIRROR}"
    git clone --mirror "${XCMAX_ROOT}" "${RUNTIME_GIT_MIRROR}" >/dev/null 2>&1 || true
  fi
fi
log "同步 FHD 配置 → ${RUNTIME_FHD_CONFIG_ROOT}"
mkdir -p "${RUNTIME_FHD_CONFIG_ROOT}"
rsync -a --delete "${FHD_ROOT}/config/" "${RUNTIME_FHD_CONFIG_ROOT}/"
log "同步 FHD 巡检运行时 → ${RUNTIME_FHD_ROOT}"
mkdir -p "${RUNTIME_FHD_ROOT}"
for d in XCAGI app mods static templates resources scripts frontend; do
  if [[ -d "${FHD_ROOT}/${d}" ]]; then
    mkdir -p "${RUNTIME_FHD_ROOT}/${d}"
    rsync -a --delete \
      --exclude ".pytest_cache/" \
      --exclude "__pycache__/" \
      --exclude ".mypy_cache/" \
      --exclude ".ruff_cache/" \
      --exclude ".vite/" \
      --exclude "coverage/" \
      --exclude "coverage-current/" \
      --exclude "coverage-target/" \
      --exclude "coverage-usechatview/" \
      --exclude "test-results/" \
      --exclude "build/" \
      "${FHD_ROOT}/${d}/" "${RUNTIME_FHD_ROOT}/${d}/"
  fi
done
find "${FHD_ROOT}" -maxdepth 1 -type f -print0 | xargs -0 -I{} cp "{}" "${RUNTIME_FHD_ROOT}/"
ln -sfn "${FHD_ROOT}/.venv" "${RUNTIME_FHD_ROOT}/.venv"
if [[ "${MODSTORE_DAILY_FORCE_ANDROID_SDK_SYNC:-0}" == "1" || ! -x "${RUNTIME_ANDROID_SDK_ROOT}/emulator/emulator" ]]; then
  if [[ -x "${RUNTIME_ANDROID_SDK_ROOT}/platform-tools/adb" ]]; then
    "${RUNTIME_ANDROID_SDK_ROOT}/platform-tools/adb" emu kill >/dev/null 2>&1 || true
    "${RUNTIME_ANDROID_SDK_ROOT}/platform-tools/adb" kill-server >/dev/null 2>&1 || true
    sleep 2
  fi
  log "同步 Android SDK → ${RUNTIME_ANDROID_SDK_ROOT}"
  rm -rf "${RUNTIME_ANDROID_SDK_ROOT}"
  mkdir -p "$(dirname "${RUNTIME_ANDROID_SDK_ROOT}")"
  /usr/bin/ditto "${FHD_ROOT}/mobile-android/.toolchain/android-sdk" "${RUNTIME_ANDROID_SDK_ROOT}"
else
  log "Android SDK 已存在 → ${RUNTIME_ANDROID_SDK_ROOT}"
fi
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
  _env_snapshot_append_file "${f}"
done

# Derive mail aliases from the generated, quoted snapshot. This keeps launchd,
# manual triggers, SMTP senders and IMAP pollers on the same credential set.
set +u
set -a
. "${ENV_SNAPSHOT}"
set +a
set -u
_env_snapshot_put SMTP_HOST "${SMTP_HOST:-${MODSTORE_SMTP_HOST:-}}"
_env_snapshot_put SMTP_PORT "${SMTP_PORT:-${MODSTORE_SMTP_PORT:-}}"
_env_snapshot_put SMTP_USER "${SMTP_USER:-${MODSTORE_SMTP_USER:-}}"
_env_snapshot_put SMTP_PASSWORD "${SMTP_PASSWORD:-${MODSTORE_SMTP_PASSWORD:-}}"
_env_snapshot_put MODSTORE_IMAP_HOST "${MODSTORE_IMAP_HOST:-imap.qq.com}"
_env_snapshot_put MODSTORE_IMAP_PORT "${MODSTORE_IMAP_PORT:-993}"
_env_snapshot_put MODSTORE_IMAP_USER "${MODSTORE_IMAP_USER:-${MODSTORE_SMTP_USER:-${SMTP_USER:-}}}"
_env_snapshot_put MODSTORE_IMAP_PASSWORD "${MODSTORE_IMAP_PASSWORD:-${MODSTORE_SMTP_PASSWORD:-${SMTP_PASSWORD:-}}}"

_env_snapshot_put MODSTORE_RUNTIME_STATE_ROOT "${STATE_ROOT}"
_env_snapshot_put MODSTORE_RUNTIME_DB_PATH "${RUNTIME_DB_PATH}"
_env_snapshot_put MODSTORE_RUNTIME_DIR "${RUNTIME_VAR_ROOT}"
_env_snapshot_put MODSTORE_EVENT_OUTBOX_PATH "${RUNTIME_EVENT_OUTBOX_PATH}"
_env_snapshot_put MODSTORE_WEBHOOK_EVENTS_DIR "${RUNTIME_WEBHOOK_EVENTS_DIR}"
_env_snapshot_put MODSTORE_RUNTIME_CONFIG_ROOT "${RUNTIME_FHD_CONFIG_ROOT}"
_env_snapshot_put MODSTORE_GIT_REPO_ROOT "${XCMAX_ROOT}"
_env_snapshot_put MODSTORE_RELEASE_TRAIN_JSON "${RUNTIME_FHD_CONFIG_ROOT}/release_train.json"
_env_snapshot_put MODSTORE_TIME_RAIL_GRAPH_JSON "${RUNTIME_FHD_CONFIG_ROOT}/time_rail_workflow_graph.json"
_env_snapshot_put MODSTORE_TIME_RAIL_RUNTIME_JSON "${STATE_ROOT}/time_rail_runtime.json"
_env_snapshot_put MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE "${POST_DEPLOY_SMOKE_STATE_FILE}"
_env_snapshot_put MODSTORE_SURFACE_AUDIT_STATE_ROOT "${SURFACE_AUDIT_STATE_ROOT}"
_env_snapshot_put MODSTORE_SURFACE_AUDIT_PIDS_DIR "${SURFACE_AUDIT_STATE_ROOT}/pids"
_env_snapshot_put MODSTORE_SURFACE_AUDIT_LOG_DIR "${SURFACE_AUDIT_STATE_ROOT}/logs"
_env_snapshot_put MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR "${SURFACE_AUDIT_STATE_ROOT}/digest-surfaces"
_env_snapshot_put MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC "1800"
_env_snapshot_put MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS "90000"
_env_snapshot_put MODSTORE_DAILY_SURFACE_AUDIT_RETRIES "2"
_env_snapshot_put MODSTORE_DAILY_SURFACE_ANALYSIS_TIMEOUT_SEC "90"
_env_snapshot_put MODSTORE_DIGEST_HTTP_TIMEOUT_SEC "1800"
_env_snapshot_put MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS "240"
_env_snapshot_put MODSTORE_DAILY_MEETING_OUTER_TIMEOUT_SECONDS "300"
_env_snapshot_put MODSTORE_DAILY_MEETING_USE_EMPLOYEE_EXECUTOR "0"
_env_snapshot_put MODSTORE_ALL_HANDS_EMPLOYEE_TIMEOUT_SEC "60"
_env_snapshot_put XCAGI_ANDROID_EMULATOR_PID_FILE "${SURFACE_AUDIT_STATE_ROOT}/android-emulator.pid"
_env_snapshot_put XCAGI_ANDROID_EMULATOR_LOG_FILE "${SURFACE_AUDIT_STATE_ROOT}/android-emulator.log"
_env_snapshot_put MODSTORE_ANDROID_EMULATOR_START_SCRIPT "${ANDROID_START_COPY}"
_env_snapshot_put XCAGI_FHD_ROOT "${RUNTIME_FHD_ROOT}"
_env_snapshot_put XCMAX_MONOREPO_ROOT "${RUNTIME_ROOT}"
_env_snapshot_put XCAGI_ANDROID_SDK_ROOT "${RUNTIME_ANDROID_SDK_ROOT}"
_env_snapshot_put ANDROID_HOME "${RUNTIME_ANDROID_SDK_ROOT}"
_env_snapshot_put ANDROID_SDK_ROOT "${RUNTIME_ANDROID_SDK_ROOT}"
_env_snapshot_put SURFACE_AUDIT_ANDROID_ADB "${RUNTIME_ANDROID_SDK_ROOT}/platform-tools/adb"
_env_snapshot_put MODSTORE_DEPLOY_ROOT "${RUNTIME_DEPLOY_ROOT}"
_env_snapshot_put MODSTORE_REPO_ROOT "${RUNTIME_DEPLOY_ROOT}"
_env_snapshot_put MODSTORE_SYNC_DEPLOY_BASH "bash ${RUNTIME_DEPLOY_ROOT}/scripts/trigger_server_git_sync.sh"
_env_snapshot_put MODSTORE_DB_PATH "${RUNTIME_DB_PATH}"
_env_snapshot_put DATABASE_URL "sqlite:////${RUNTIME_DB_PATH#/}"

PARA_API_BASE="${MODSTORE_PARA_API_BASE:-}"
PARA_RUNTIME_DB_FILE="${HOME}/XCMAX-runtime/para-api/devfleet/api/data/devfleet.db"
PARA_DESKTOP_DB_FILE="${HOME}/Library/Application Support/com.devfleet.desktop/devfleet.db"
if [[ -n "${MODSTORE_PARA_DB_FILE:-}" ]]; then
  PARA_DB_FILE="${MODSTORE_PARA_DB_FILE}"
elif [[ -n "${DEVFLEET_DB_FILE:-}" ]]; then
  PARA_DB_FILE="${DEVFLEET_DB_FILE}"
elif [[ -f "${PARA_RUNTIME_DB_FILE}" ]]; then
  PARA_DB_FILE="${PARA_RUNTIME_DB_FILE}"
else
  PARA_DB_FILE="${PARA_DESKTOP_DB_FILE}"
fi
if [[ -z "${PARA_API_BASE}" ]]; then
  if /usr/bin/curl -fsS --max-time 2 "http://127.0.0.1:3001/api/health" >/dev/null 2>&1; then
    PARA_API_BASE="http://127.0.0.1:3001"
  fi
fi
PARA_DEVICE_ID="${MODSTORE_PARA_DEVICE_ID:-}"
if [[ -z "${PARA_DEVICE_ID}" && -f "${PARA_DB_FILE}" ]] && command -v sqlite3 >/dev/null 2>&1; then
  PARA_DEVICE_ID="$(
    sqlite3 "${PARA_DB_FILE}" \
      "select id from devices where status='online' and activated=1 and connection_allowed=1 order by is_primary desc, last_seen desc limit 1;" \
      2>/dev/null || true
  )"
fi
if [[ -n "${PARA_API_BASE}" ]]; then
  _env_snapshot_put MODSTORE_PARA_API_BASE "${PARA_API_BASE}"
fi
if [[ -n "${PARA_DEVICE_ID}" ]]; then
  _env_snapshot_put MODSTORE_PARA_DEVICE_ID "${PARA_DEVICE_ID}"
fi
if [[ -f "${PARA_DB_FILE}" ]]; then
  _env_snapshot_put MODSTORE_PARA_DB_FILE "${PARA_DB_FILE}"
fi
PARA_EXISTING_BARE="${HOME}/XCMAX-runtime/git/XCMAX.bare.git"
if [[ -d "${PARA_EXISTING_BARE}/objects" ]]; then
  PARA_REPO_URL="${MODSTORE_PARA_REPO_URL:-file://${PARA_EXISTING_BARE}}"
elif [[ -d "${RUNTIME_GIT_MIRROR}/objects" ]]; then
  PARA_REPO_URL="${MODSTORE_PARA_REPO_URL:-file://${RUNTIME_GIT_MIRROR}}"
else
  PARA_REPO_URL="${MODSTORE_PARA_REPO_URL:-file://${XCMAX_ROOT}}"
fi
PARA_BRANCH="${MODSTORE_PARA_BRANCH:-}"
if [[ -z "${PARA_BRANCH}" && -d "${XCMAX_ROOT}/.git" ]] && command -v git >/dev/null 2>&1; then
  PARA_BRANCH="$(git -C "${XCMAX_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ "${PARA_BRANCH}" == "HEAD" ]] && PARA_BRANCH=""
fi
_env_snapshot_put MODSTORE_PARA_REPO_URL "${PARA_REPO_URL}"
_env_snapshot_put MODSTORE_PARA_BRANCH "${PARA_BRANCH:-main}"
_env_snapshot_put MODSTORE_SELF_MAINTENANCE_ALLOW_DESKTOP_REPO "${MODSTORE_SELF_MAINTENANCE_ALLOW_DESKTOP_REPO:-1}"
_env_snapshot_put MODSTORE_PARA_AUTH_LOCAL_MINT "${MODSTORE_PARA_AUTH_LOCAL_MINT:-1}"
cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
# 由 install_modstore_daily_launchd.sh 生成 — 勿手改
if [[ "\${MODSTORE_DAILY_ENV_CLEANROOM:-0}" != "1" ]]; then
  exec /usr/bin/env -i \
    HOME="${HOME}" \
    PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    MODSTORE_DAILY_ENV_CLEANROOM=1 \
    /bin/bash "\$0"
fi
export MODSTORE_DAILY_FOREGROUND=1
export MODSTORE_DAILY_FHD_ROOT="${RUNTIME_FHD_ROOT}"
export MODSTORE_DAILY_XCMAX_ROOT="${RUNTIME_ROOT}"
export MODSTORE_DAILY_SCRIPT_DIR_OVERRIDE="${SCRIPT_DIR}"
export MODSTORE_DAILY_ENV_SNAPSHOT="${ENV_SNAPSHOT}"
export MODSTORE_DAILY_SKIP_ENV_FILES=1
export MODSTORE_RUNTIME_ROOT="${RUNTIME_ROOT}"
export MODSTORE_RUNTIME_STATE_ROOT="${STATE_ROOT}"
export MODSTORE_RUNTIME_DB_PATH="${RUNTIME_DB_PATH}"
export MODSTORE_RUNTIME_DIR="${RUNTIME_VAR_ROOT}"
export MODSTORE_EVENT_OUTBOX_PATH="${RUNTIME_EVENT_OUTBOX_PATH}"
export MODSTORE_WEBHOOK_EVENTS_DIR="${RUNTIME_WEBHOOK_EVENTS_DIR}"
export MODSTORE_RUNTIME_CONFIG_ROOT="${RUNTIME_FHD_CONFIG_ROOT}"
export MODSTORE_GIT_REPO_ROOT="${XCMAX_ROOT}"
export MODSTORE_RELEASE_TRAIN_JSON="${RUNTIME_FHD_CONFIG_ROOT}/release_train.json"
export MODSTORE_TIME_RAIL_GRAPH_JSON="${RUNTIME_FHD_CONFIG_ROOT}/time_rail_workflow_graph.json"
export MODSTORE_TIME_RAIL_RUNTIME_JSON="${STATE_ROOT}/time_rail_runtime.json"
export MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE="${POST_DEPLOY_SMOKE_STATE_FILE}"
export MODSTORE_SURFACE_AUDIT_STATE_ROOT="${SURFACE_AUDIT_STATE_ROOT}"
export MODSTORE_SURFACE_AUDIT_PIDS_DIR="${SURFACE_AUDIT_STATE_ROOT}/pids"
export MODSTORE_SURFACE_AUDIT_LOG_DIR="${SURFACE_AUDIT_STATE_ROOT}/logs"
export MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR="${SURFACE_AUDIT_STATE_ROOT}/digest-surfaces"
export MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC="1800"
export MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS="90000"
export MODSTORE_DAILY_SURFACE_AUDIT_RETRIES="2"
export MODSTORE_DAILY_SURFACE_ANALYSIS_TIMEOUT_SEC="90"
export MODSTORE_DIGEST_HTTP_TIMEOUT_SEC="1800"
export MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS="240"
export MODSTORE_DAILY_MEETING_OUTER_TIMEOUT_SECONDS="300"
export MODSTORE_DAILY_MEETING_USE_EMPLOYEE_EXECUTOR="0"
export MODSTORE_ALL_HANDS_EMPLOYEE_TIMEOUT_SEC="60"
export XCAGI_ANDROID_EMULATOR_PID_FILE="${SURFACE_AUDIT_STATE_ROOT}/android-emulator.pid"
export XCAGI_ANDROID_EMULATOR_LOG_FILE="${SURFACE_AUDIT_STATE_ROOT}/android-emulator.log"
export MODSTORE_ANDROID_EMULATOR_START_SCRIPT="${ANDROID_START_COPY}"
export XCAGI_FHD_ROOT="${RUNTIME_FHD_ROOT}"
export XCMAX_MONOREPO_ROOT="${RUNTIME_ROOT}"
export XCAGI_ANDROID_SDK_ROOT="${RUNTIME_ANDROID_SDK_ROOT}"
export ANDROID_HOME="${RUNTIME_ANDROID_SDK_ROOT}"
export ANDROID_SDK_ROOT="${RUNTIME_ANDROID_SDK_ROOT}"
export SURFACE_AUDIT_ANDROID_ADB="${RUNTIME_ANDROID_SDK_ROOT}/platform-tools/adb"
export MODSTORE_DEPLOY_ROOT="${RUNTIME_DEPLOY_ROOT}"
export MODSTORE_REPO_ROOT="${RUNTIME_DEPLOY_ROOT}"
export MODSTORE_SYNC_DEPLOY_BASH="bash ${RUNTIME_DEPLOY_ROOT}/scripts/trigger_server_git_sync.sh"
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
