#!/usr/bin/env bash
# 安装 Para API + 健康型 watchdog。API 本身不 KeepAlive，所有修复/重启由健康检查仲裁。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARA_API_ROOT="${PARA_API_ROOT:-${HOME}/XCMAX-runtime/para-api/devfleet}"
PARA_RUNTIME_ROOT="$(cd "${PARA_API_ROOT}/.." && pwd)"
PARA_LOG_DIR="${PARA_RUNTIME_ROOT}/logs"
PARA_WORKSPACE_ROOT="${PARA_WORKSPACE_ROOT:-${HOME}/XCMAX-runtime/para-main-agent/workspace}"
SUPPORT_DIR="${HOME}/Library/Application Support/XCMAX"
WATCHDOG_COPY="${SUPPORT_DIR}/para_health_watchdog.sh"
CLEANUP_COPY="${SUPPORT_DIR}/para_runtime_cleanup.sh"
API_WRAPPER="${SUPPORT_DIR}/run-para-api.sh"
WATCHDOG_WRAPPER="${SUPPORT_DIR}/run-para-health-watchdog.sh"
CLEANUP_WRAPPER="${SUPPORT_DIR}/run-para-cleanup.sh"
API_PLIST="${HOME}/Library/LaunchAgents/com.xcmax.para-api.plist"
WATCHDOG_PLIST="${HOME}/Library/LaunchAgents/com.xcmax.para-health-watchdog.plist"
CLEANUP_PLIST="${HOME}/Library/LaunchAgents/com.xcmax.para-cleanup.plist"
NODE_BIN="${PARA_NODE_BIN:-${HOME}/.local/bin/node}"
NPM_BIN="${PARA_NPM_BIN:-${HOME}/.local/bin/npm}"
UID_NUM="$(id -u)"

log() { printf '[para-install] %s\n' "$*"; }
[[ -d "${PARA_API_ROOT}" ]] || { log "Para API 根不存在: ${PARA_API_ROOT}"; exit 1; }
[[ -x "${NODE_BIN}" ]] || { log "Node 不存在: ${NODE_BIN}"; exit 1; }
[[ -x "${NPM_BIN}" ]] || { log "npm 不存在: ${NPM_BIN}"; exit 1; }

mkdir -p "${SUPPORT_DIR}" "${PARA_LOG_DIR}" "${HOME}/Library/LaunchAgents"
cp "${SCRIPT_DIR}/para_health_watchdog.sh" "${WATCHDOG_COPY}"
cp "${SCRIPT_DIR}/para_runtime_cleanup.sh" "${CLEANUP_COPY}"
chmod +x "${WATCHDOG_COPY}"
chmod +x "${CLEANUP_COPY}"

cat > "${API_WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="$(dirname "${NODE_BIN}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PORT="3001"
export DEVFLEET_HOST="0.0.0.0"
export DEVFLEET_DB_FILE="${PARA_API_ROOT}/api/data/devfleet.db"
cd "${PARA_API_ROOT}"
exec "${NPM_BIN}" run server
EOF
chmod +x "${API_WRAPPER}"

cat > "${WATCHDOG_WRAPPER}" <<EOF
#!/usr/bin/env bash
export HOME="${HOME}"
export PATH="$(dirname "${NODE_BIN}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PARA_API_ROOT="${PARA_API_ROOT}"
export PARA_NODE_BIN="${NODE_BIN}"
export PARA_NPM_BIN="${NPM_BIN}"
export PARA_CLEANUP_COMMAND="${CLEANUP_WRAPPER}"
exec /bin/bash "${WATCHDOG_COPY}"
EOF
chmod +x "${WATCHDOG_WRAPPER}"

cat > "${CLEANUP_WRAPPER}" <<EOF
#!/usr/bin/env bash
export HOME="${HOME}"
export PATH="$(dirname "${NODE_BIN}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PARA_API_ROOT="${PARA_API_ROOT}"
export PARA_RUNTIME_ROOT="${PARA_RUNTIME_ROOT}"
export PARA_NODE_BIN="${NODE_BIN}"
export PARA_WORKSPACE_ROOT="${PARA_WORKSPACE_ROOT}"
exec /bin/bash "${CLEANUP_COPY}" "\$@"
EOF
chmod +x "${CLEANUP_WRAPPER}"

sed \
  -e "s|__XCMAX_RUN_PARA_API__|${API_WRAPPER}|g" \
  -e "s|__XCMAX_PARA_LOG_DIR__|${PARA_LOG_DIR}|g" \
  -e "s|__XCMAX_PARA_ROOT__|${PARA_API_ROOT}|g" \
  "${SCRIPT_DIR}/com.xcmax.para-api.plist" > "${API_PLIST}"
sed \
  -e "s|__XCMAX_RUN_PARA_WATCHDOG__|${WATCHDOG_WRAPPER}|g" \
  -e "s|__XCMAX_PARA_LOG_DIR__|${PARA_LOG_DIR}|g" \
  -e "s|__XCMAX_PARA_ROOT__|${PARA_API_ROOT}|g" \
  "${SCRIPT_DIR}/com.xcmax.para-health-watchdog.plist" > "${WATCHDOG_PLIST}"
sed \
  -e "s|__XCMAX_RUN_PARA_CLEANUP__|${CLEANUP_WRAPPER}|g" \
  -e "s|__XCMAX_PARA_LOG_DIR__|${PARA_LOG_DIR}|g" \
  -e "s|__XCMAX_PARA_ROOT__|${PARA_API_ROOT}|g" \
  "${SCRIPT_DIR}/com.xcmax.para-cleanup.plist" > "${CLEANUP_PLIST}"

# 先卸载旧的 KeepAlive=true API，立即终止 ABI 崩溃循环；watchdog 负责修复后拉起。
launchctl bootout "gui/${UID_NUM}/com.xcmax.para-cleanup" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}/com.xcmax.para-health-watchdog" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}/com.xcmax.para-api" 2>/dev/null || true
for _ in $(seq 1 20); do
  if ! launchctl print "gui/${UID_NUM}/com.xcmax.para-api" >/dev/null 2>&1 \
     && ! launchctl print "gui/${UID_NUM}/com.xcmax.para-health-watchdog" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
# npm/tsx 会派生子进程；旧 plist 被卸载后，清掉仍占用 3001 且命令行属于 Para 根的孤儿。
for pid in $(lsof -tiTCP:3001 -sTCP:LISTEN 2>/dev/null || true); do
  command_line="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  case "${command_line}" in
    *"${PARA_API_ROOT}"*) kill "${pid}" 2>/dev/null || true ;;
  esac
done
for _ in $(seq 1 20); do
  if ! lsof -tiTCP:3001 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
launchctl bootstrap "gui/${UID_NUM}" "${API_PLIST}"
launchctl bootstrap "gui/${UID_NUM}" "${WATCHDOG_PLIST}"
launchctl bootstrap "gui/${UID_NUM}" "${CLEANUP_PLIST}"
launchctl enable "gui/${UID_NUM}/com.xcmax.para-api" 2>/dev/null || true
launchctl enable "gui/${UID_NUM}/com.xcmax.para-health-watchdog" 2>/dev/null || true
launchctl enable "gui/${UID_NUM}/com.xcmax.para-cleanup" 2>/dev/null || true

for _ in $(seq 1 120); do
  if /usr/bin/curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:3001/api/health >/dev/null 2>&1; then
    log "Para API 已健康；watchdog 已接管依赖修复和受限重启"
    exit 0
  fi
  sleep 1
done
log "Para API 120 秒内未恢复；查看 ${HOME}/Library/Logs/XCMAX/para-health-watchdog.log"
exit 1
