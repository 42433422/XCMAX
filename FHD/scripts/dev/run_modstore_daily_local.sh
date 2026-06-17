#!/usr/bin/env bash
# 本地日更全链路：MODstore :8788 + APScheduler（03:15 归档 / 08:00 摘要邮件 / 08:15 补丁 / 08:25 编排）
# 用法：bash FHD/scripts/dev/run_modstore_daily_local.sh
# 另开终端：export $(grep -v '^#' FHD/XCAGI/.env.local-market | xargs) && 启动 FHD API
set -euo pipefail

SCRIPT_DIR="${MODSTORE_DAILY_SCRIPT_DIR_OVERRIDE:-$(cd "$(dirname "$0")" && pwd)}"
FHD_ROOT="${MODSTORE_DAILY_FHD_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
XCMAX_ROOT="${MODSTORE_DAILY_XCMAX_ROOT:-$(cd "${FHD_ROOT}/.." && pwd)}"
MODSTORE_RUNTIME_ROOT="${MODSTORE_RUNTIME_ROOT:-$HOME/XCMAX-runtime/modstore-daily}"
_WS_MODSTORE="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy"
_ARCHIVE_MODSTORE="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
_RUNTIME_MODSTORE="${MODSTORE_RUNTIME_ROOT}/MODstore_deploy"
if [[ -d "${_RUNTIME_MODSTORE}/modstore_server" ]]; then
  MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${_RUNTIME_MODSTORE}}"
elif [[ -d "${_WS_MODSTORE}/modstore_server" ]]; then
  MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${_WS_MODSTORE}}"
else
  MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${_ARCHIVE_MODSTORE}}"
fi
MODSTORE_PORT="${MODSTORE_PORT:-8788}"
MARKET_PORT="${MARKET_PORT:-5176}"
PY="${FHD_ROOT}/.venv/bin/python"

log() { printf '[daily-local] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]] || fail "MODstore_deploy 未找到: ${MODSTORE_DEPLOY_ROOT}"
[[ -x "${PY}" ]] || fail "FHD venv 未找到: ${PY}"

if ! "${PY}" -c "import apscheduler" 2>/dev/null; then
  log "安装 apscheduler（日更 cron 依赖）…"
  "${PY}" -m pip install -q apscheduler
fi
if ! "${PY}" -c "import cursor_sdk" 2>/dev/null; then
  log "安装 cursor-sdk（vibe-coding-maintainer Cursor 委托改码）…"
  "${PY}" -m pip install -q cursor-sdk
fi

export XCMAX_MONOREPO_ROOT="${XCMAX_MONOREPO_ROOT:-${XCMAX_ROOT}}"
# 日更 git 操作根：指向 xcagi-modstore 干净 git 仓（=MODstore_deploy），否则 cr_git_pipeline/编排无 git 仓可用 → 空跳。
# 仅当该目录确为 git 工作树时才用，避免误落到非 git 路径。
if [[ -d "${MODSTORE_DEPLOY_ROOT}/.git" ]]; then
  export MODSTORE_REPO_ROOT="${MODSTORE_REPO_ROOT:-${MODSTORE_DEPLOY_ROOT}}"
else
  export MODSTORE_REPO_ROOT="${MODSTORE_REPO_ROOT:-${XCMAX_ROOT}}"
fi
# 干净分支模型（见 MODstore_deploy/BRANCHING.md）：长期 auto/daily + 每日单 PR，CR 不逐个开 PR。
export MODSTORE_DAILY_BRANCH="${MODSTORE_DAILY_BRANCH:-auto/daily}"
export MODSTORE_CR_GIT_AUTO_PR="${MODSTORE_CR_GIT_AUTO_PR:-1}"
export MODSTORE_CR_BRANCH_PREFIX="${MODSTORE_CR_BRANCH_PREFIX:-cr}"
export MODSTORE_BRANCH_CLEANUP_KEEP_DAYS="${MODSTORE_BRANCH_CLEANUP_KEEP_DAYS:-7}"
export MODSTORE_API_PORT="${MODSTORE_PORT}"
export XCAGI_MARKET_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODSTORE_LOCAL_AUTOMATION=1
export MODSTORE_LOCAL_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODSTORE_DIGEST_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODSTORE_ALL_HANDS_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODSTORE_RUN_BACKGROUND_JOBS=1

# 发信：优先 .env.production 的 QQ SMTP（用户已配置）；默认真发，不设 DEBUG
_load_modstore_env_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//$'\r'/}"
    line="${line%%#*}"
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" || "$line" != *=* ]] && continue
    local k="${line%%=*}" v="${line#*=}"
    k="$(echo "$k" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    v="$(echo "$v" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
    [[ -n "$k" ]] && export "$k=$v"
  done < "$f"
}
SNAPSHOT_LOADED=0
if [[ -n "${MODSTORE_DAILY_ENV_SNAPSHOT:-}" && -f "${MODSTORE_DAILY_ENV_SNAPSHOT}" ]]; then
  _load_modstore_env_file "${MODSTORE_DAILY_ENV_SNAPSHOT}"
  SNAPSHOT_LOADED=1
fi
if [[ "${SNAPSHOT_LOADED}" != "1" && "${MODSTORE_DAILY_SKIP_ENV_FILES:-0}" != "1" ]]; then
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env"
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env.production"
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env.production.synced"
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env.daily-closure"
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env.local"
fi
# 本地 Mac 日更必须用 SQLite；生产同步 env 里的 DATABASE_URL 仅服务器有效
if [[ -n "${MODSTORE_DB_PATH:-}" ]]; then
  export MODSTORE_DB_PATH
  unset DATABASE_URL DATABASE_USER DATABASE_PASSWORD DATABASE_HOST DATABASE_PORT DATABASE_NAME
fi
# 本地无 Redis 时关闭 Streams 双写，避免 incident_bus 刷 Connection refused
export MODSTORE_EVENT_STREAM_ENABLED="${MODSTORE_EVENT_STREAM_ENABLED:-0}"
if [[ "${MODSTORE_EVENT_STREAM_ENABLED}" == "0" ]]; then
  unset REDIS_URL REDIS_PORT MODSTORE_REDIS_URL MODSTORE_EVENT_STREAM_URL CACHE_REDIS_URL XCAGI_REDIS_URL MODSTORE_VECTOR_REDIS_URL 2>/dev/null || true
fi
export MODSTORE_INTERNAL_API_BASE="${MODSTORE_INTERNAL_API_BASE:-http://127.0.0.1:${MODSTORE_PORT}}"
export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:${MODSTORE_PORT}}"
export MODSTORE_LOCAL_BASE_URL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:${MODSTORE_PORT}}"
export MODSTORE_DIGEST_BASE_URL="${MODSTORE_DIGEST_BASE_URL:-http://127.0.0.1:${MODSTORE_PORT}}"
# 真 SMTP 授权码（覆盖 .env.production 里的 your-* 占位符）；勿提交 git
if [[ "${SNAPSHOT_LOADED}" != "1" && "${MODSTORE_DAILY_SKIP_ENV_FILES:-0}" != "1" ]]; then
  _load_modstore_env_file "${MODSTORE_DEPLOY_ROOT}/.env.smtp.local"
  _load_modstore_env_file "${FHD_ROOT}/XCAGI/.env.smtp.local"
  _load_modstore_env_file "${FHD_ROOT}/XCAGI/.env.cursor.local"
fi
export MODSTORE_EMAIL_DEBUG="${MODSTORE_EMAIL_DEBUG:-0}"
if [[ "${MODSTORE_EMAIL_DEBUG}" == "0" && -z "${MODSTORE_SMTP_PASSWORD:-}" ]]; then
  log "WARN: MODSTORE_SMTP_PASSWORD 未设 → 运行: bash ${MODSTORE_DEPLOY_ROOT}/scripts/pull_prod_env_for_local.sh"
fi
if [[ ! -f "${MODSTORE_DEPLOY_ROOT}/.env.production.synced" ]]; then
  log "WARN: 无 .env.production.synced → bash ${MODSTORE_DEPLOY_ROOT}/scripts/pull_prod_env_for_local.sh（从服务器拉 SMTP/凭证）"
fi
export MODSTORE_DAILY_DIGEST_ENABLED="${MODSTORE_DAILY_DIGEST_ENABLED:-1}"
export MODSTORE_DAILY_VIBE_PREP_ENABLED="${MODSTORE_DAILY_VIBE_PREP_ENABLED:-1}"
export MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED="${MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED:-1}"
export MODSTORE_DAILY_VIBE_EXECUTE_ENABLED="${MODSTORE_DAILY_VIBE_EXECUTE_ENABLED:-1}"
export MODSTORE_RELEASE_TRAIN_ENABLED="${MODSTORE_RELEASE_TRAIN_ENABLED:-1}"
export MODSTORE_DAILY_MEETING_ENABLED="${MODSTORE_DAILY_MEETING_ENABLED:-1}"
export MODSTORE_DAILY_SURFACE_AUDIT_ENABLED="${MODSTORE_DAILY_SURFACE_AUDIT_ENABLED:-1}"
export MODSTORE_DAILY_SURFACE_PPT_ENABLED="${MODSTORE_DAILY_SURFACE_PPT_ENABLED:-1}"
# 三端「获客面」巡检目标：P-W 官网静态页 + P-S/P-App 市场 SPA 公开页，统一由公网站 xiu-ci.com 提供。
# 注意：不要指向 FHD 企业后端 :5100 —— 它服务的是「企业版登录 SPA」，巡检会全站抓到登录页 + 401（误报）。
# 如需巡检本地市场 SPA，请显式设 MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL 为对应本地源。
export MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL="${MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL:-https://xiu-ci.com}"
export MODSTORE_DAILY_SURFACE_AUDIT_MODE="${MODSTORE_DAILY_SURFACE_AUDIT_MODE:-daily}"
export MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE="${MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE:-1}"
export MODSTORE_SURFACE_AUDIT_SKIP_CATALOG="${MODSTORE_SURFACE_AUDIT_SKIP_CATALOG:-0}"
export MODSTORE_SURFACE_AUDIT_CATALOG_MAX="${MODSTORE_SURFACE_AUDIT_CATALOG_MAX:-3}"
export MODSTORE_SURFACE_AUDIT_STOP_AFTER="${MODSTORE_SURFACE_AUDIT_STOP_AFTER:-1}"
export MODSTORE_AUTOMATION_PRIMARY="${MODSTORE_AUTOMATION_PRIMARY:-local_mac}"
export MODSTORE_AUTOMATION_ROLE="${MODSTORE_AUTOMATION_ROLE:-local_mac}"
export MODSTORE_SYNC_DEPLOY_BASH="${MODSTORE_SYNC_DEPLOY_BASH:-bash ${MODSTORE_DEPLOY_ROOT}/scripts/trigger_server_git_sync.sh}"
export MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE="${MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE:-primary}"
export MODSTORE_DAILY_ORCHESTRATOR_ENABLED="${MODSTORE_DAILY_ORCHESTRATOR_ENABLED:-1}"
# Git push / PR / auto-merge 闭环（BR → STG → APPR → MERGE）
export MODSTORE_AUTO_PR_ENABLED="${MODSTORE_AUTO_PR_ENABLED:-1}"
export MODSTORE_AUTO_PR_BASE_BRANCH="${MODSTORE_AUTO_PR_BASE_BRANCH:-main}"
export MODSTORE_DEPLOY_PUSH_REMOTE="${MODSTORE_DEPLOY_PUSH_REMOTE:-origin}"
export MODSTORE_DEPLOY_PUSH_BRANCH_PREFIX="${MODSTORE_DEPLOY_PUSH_BRANCH_PREFIX:-auto/daily-}"
export MODSTORE_OPS_STAGED_AUTO_APPROVE="${MODSTORE_OPS_STAGED_AUTO_APPROVE:-1}"
export MODSTORE_OPS_STAGED_AUTO_MAX_FILES="${MODSTORE_OPS_STAGED_AUTO_MAX_FILES:-24}"
export MODSTORE_SLO_HALT_AUTO_MERGE="${MODSTORE_SLO_HALT_AUTO_MERGE:-1}"
export MODSTORE_RELEASE_SLO_HALT="${MODSTORE_RELEASE_SLO_HALT:-1}"
export MODSTORE_CR_GIT_BRANCH_ENABLED="${MODSTORE_CR_GIT_BRANCH_ENABLED:-1}"
export MODSTORE_CR_GIT_APPLY_COMMIT="${MODSTORE_CR_GIT_APPLY_COMMIT:-1}"
export MODSTORE_AUTO_APPROVE_ENABLED="${MODSTORE_AUTO_APPROVE_ENABLED:-1}"
export MODSTORE_AUTO_APPROVE_REQUIRE_CI="${MODSTORE_AUTO_APPROVE_REQUIRE_CI:-1}"
export MODSTORE_CR_NARROW_CI_ENABLED="${MODSTORE_CR_NARROW_CI_ENABLED:-1}"
export MODSTORE_INBOX_POLL_ENABLED="${MODSTORE_INBOX_POLL_ENABLED:-1}"
export MODSTORE_POST_DEPLOY_SMOKE_ENABLED="${MODSTORE_POST_DEPLOY_SMOKE_ENABLED:-1}"
export MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED="${MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED:-1}"
export MODSTORE_DEPLOY_HEALTH_URL="${MODSTORE_DEPLOY_HEALTH_URL:-http://127.0.0.1:${MODSTORE_PORT}/api/health}"
export MODSTORE_POST_DEPLOY_MARKET_URL="${MODSTORE_POST_DEPLOY_MARKET_URL:-https://xiu-ci.com/market/download}"
export MODSTORE_LINE_PRIMARY_LINES="${MODSTORE_LINE_PRIMARY_LINES:-P-S}"
export MODSTORE_LINE_SHADOW_LINES="${MODSTORE_LINE_SHADOW_LINES:-P-W,P-App,S-R}"
export MODSTORE_SURFACE_AUDIT_AUTO_START="${MODSTORE_SURFACE_AUDIT_AUTO_START:-1}"
export MODSTORE_SURFACE_AUDIT_ANDROID="${MODSTORE_SURFACE_AUDIT_ANDROID:-1}"
export MODSTORE_SURFACE_AUDIT_PS_ENABLED="${MODSTORE_SURFACE_AUDIT_PS_ENABLED:-1}"
export SURFACE_AUDIT_PRODUCT_SKU="${SURFACE_AUDIT_PRODUCT_SKU:-enterprise}"
export SURFACE_AUDIT_INCLUDE_ENTERPRISE="${SURFACE_AUDIT_INCLUDE_ENTERPRISE:-1}"
# 本地 Mac：.env.daily-closure 常写 :5000/:5100，但 :5000 被 AirPlay 占用、:5100 常为开发 PostgreSQL 实例 → 日更栈专用 :5102 桌面 SQLite
export SURFACE_AUDIT_API_URL="http://127.0.0.1:5102"
export SURFACE_AUDIT_ANDROID_FHD_HOST="10.0.2.2:5102"
ADB_BIN="${FHD_ROOT}/mobile-android/.toolchain/android-sdk/platform-tools/adb"
[[ -x "${ADB_BIN}" ]] || ADB_BIN="adb"
_adb_devices_has_online_target() {
  "${PY}" - "$1" <<'PY'
import re
import subprocess
import sys

adb = sys.argv[1]
try:
    out = subprocess.run(
        [adb, "devices"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    ).stdout
except Exception:
    sys.exit(2)
for line in out.splitlines():
    if re.search(r"\sdevice$", line):
        sys.exit(0)
sys.exit(1)
PY
}
if [[ "${MODSTORE_SURFACE_AUDIT_ANDROID}" != "0" ]]; then
  if ! _adb_devices_has_online_target "${ADB_BIN}"; then
    if [[ "${XCAGI_AUTO_START_EMULATOR:-1}" == "1" && -x "${FHD_ROOT}/mobile-android/.toolchain/android-sdk/emulator/emulator" ]]; then
      log "P-App 截图：无在线模拟器，尝试启动 …"
      bash "${FHD_ROOT}/scripts/dev/start_android_emulator.sh" || log "WARN: 模拟器启动失败，digest P-App 可能失败"
    fi
  fi
  if _adb_devices_has_online_target "${ADB_BIN}"; then
    export SURFACE_AUDIT_ANDROID_ADB="${ADB_BIN}"
    log "P-App 截图：adb 模拟器/真机已就绪"
  else
    log "WARN: 无 adb 设备 — P-App 日更截图将失败（bash FHD/scripts/dev/start_android_emulator.sh）"
  fi
fi
export MODSTORE_DR_PROBE_ENABLED="${MODSTORE_DR_PROBE_ENABLED:-1}"
export MODSTORE_ONDEMAND_BACKUP_ENABLED="${MODSTORE_ONDEMAND_BACKUP_ENABLED:-1}"
export MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_HIGH_RISK="${MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_HIGH_RISK:-1}"
export MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_MEDIUM_RISK="${MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_MEDIUM_RISK:-1}"
export MODSTORE_INSTALLER_PUSH_ALLOW_HIGH_RISK="${MODSTORE_INSTALLER_PUSH_ALLOW_HIGH_RISK:-1}"
export MODSTORE_EMAIL_INTAKE_ENABLED="${MODSTORE_EMAIL_INTAKE_ENABLED:-1}"
export MODSTORE_IMAP_HOST="${MODSTORE_IMAP_HOST:-imap.qq.com}"
export MODSTORE_IMAP_PORT="${MODSTORE_IMAP_PORT:-993}"
export MODSTORE_RELEASE_TRAIN_JSON="${XCMAX_ROOT}/FHD/config/release_train.json"
# auto-merge 后 GitOps 晋级（与 fhd-ci-cd gitops-image-bump 双轨；SLO 熔断时 post_merge 会 exit 1）
export MODSTORE_POST_MERGE_GITOPS_SCRIPT="${MODSTORE_POST_MERGE_GITOPS_SCRIPT:-${FHD_ROOT}/scripts/gitops/post_merge_promote.sh}"
# TLS 证书到期巡检（K 节点）：写入 .env.local 或在此处设默认路径
# 示例：MODSTORE_TLS_CERT_PATHS=/path/to/xiu-ci.com_bundle.pem
export MODSTORE_TLS_CERT_PATHS="${MODSTORE_TLS_CERT_PATHS:-}"
# vibe_edit / Cursor SDK 工作区：MODstore_deploy 上级目录（含 vibe-coding/）
export MODSTORE_TENANT_WORKSPACE_ROOT="${MODSTORE_TENANT_WORKSPACE_ROOT:-$(cd "${MODSTORE_DEPLOY_ROOT}/.." && pwd)}"
export VIBE_CODING_ROOT="${VIBE_CODING_ROOT:-${MODSTORE_TENANT_WORKSPACE_ROOT}/vibe-coding}"
export PYTHONPATH="${MODSTORE_DEPLOY_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# 强制 UTF-8 运行时：否则非 UTF-8 locale 下读取 CJK 文件名（截图/PPT）会 UnicodeEncodeError
export PYTHONUTF8=1
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
# 本地全景 dashboard（:8765/:8770/:5000/:5001/:5100 等）跨源直连 MODstore 取日更看板数据；
# Starlette CORS 在 allow_origins 之外额外匹配此 regex（放行任意 localhost 源）
export CORS_ORIGIN_REGEX="${CORS_ORIGIN_REGEX:-^https?://(127\.0\.0\.1|localhost)(:[0-9]+)?$}"
if [[ -z "${CURSOR_API_KEY:-}" ]]; then
  log "WARN: CURSOR_API_KEY 未设 → P0/Cursor 委托改码将跳过；写入 FHD/XCAGI/.env.cursor.local"
fi

log "MODstore 全量日更栈 → http://127.0.0.1:${MODSTORE_PORT}"
log "部署根 ${MODSTORE_DEPLOY_ROOT}"
log "运行时根 ${MODSTORE_RUNTIME_ROOT}"
log "Monorepo ${XCMAX_MONOREPO_ROOT}"
log "后台任务 MODSTORE_RUN_BACKGROUND_JOBS=${MODSTORE_RUN_BACKGROUND_JOBS}"

if curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" >/dev/null 2>&1; then
  sched="$(curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('scheduler_running'))" 2>/dev/null || echo '?')"
  if [[ "${MODSTORE_DAILY_FOREGROUND:-0}" != "1" && "${MODSTORE_DAILY_FORCE_RESTART:-0}" != "1" && ( "${sched}" == "True" || "${sched}" == "true" ) ]]; then
    log "MODstore 已在 :${MODSTORE_PORT} 运行且调度器已开 — 跳过重启（改配置后设 MODSTORE_DAILY_FORCE_RESTART=1）"
    exit 0
  fi
  log "检测到 :${MODSTORE_PORT} 需重启为全量日更实例（scheduler=${sched} foreground=${MODSTORE_DAILY_FOREGROUND:-0}）"
  pid="$(lsof -ti :${MODSTORE_PORT} 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    kill "${pid}" 2>/dev/null || true
    sleep 1
  fi
fi

if [[ "${MODSTORE_DAILY_FOREGROUND:-0}" == "1" ]]; then
  log "launchd 前台模式 — exec uvicorn pid=$$"
  cd "${MODSTORE_DEPLOY_ROOT}"
  exec "${PY}" -m uvicorn modstore_server.app:app --host 127.0.0.1 --port "${MODSTORE_PORT}"
fi

DAEMON_LOG_DIR="${MODSTORE_DAILY_DAEMON_LOG_DIR:-${HOME}/Library/Logs/XCMAX}"
mkdir -p "${DAEMON_LOG_DIR}"
DAEMON_LOG_PATH="${DAEMON_LOG_DIR}/modstore-daily.daemon.log"
(
  cd "${MODSTORE_DEPLOY_ROOT}"
  exec nohup "${PY}" -m uvicorn modstore_server.app:app --host 127.0.0.1 --port "${MODSTORE_PORT}" >>"${DAEMON_LOG_PATH}" 2>&1 < /dev/null
) &
UV_PID=$!
disown "${UV_PID}" 2>/dev/null || true

for _ in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" >/dev/null 2>&1; then
    sched="$(curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('scheduler_running'))" 2>/dev/null || echo '')"
    log "MODstore 就绪 pid=${UV_PID} scheduler_running=${sched}"
    log "守护日志 ${DAEMON_LOG_PATH}"
    log "手动触发摘要: curl -X POST http://127.0.0.1:5000/api/xcmax/admin/email/digest-now （需 FHD 管理员会话）"
    log "或直接 MODstore: 登录 admin 后 POST /api/admin/email/digest-now"
    exit 0
  fi
  sleep 1
done

fail "MODstore 启动超时（检查 ${MODSTORE_DEPLOY_ROOT} 依赖）"
