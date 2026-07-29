#!/usr/bin/env bash
# Para/DevFleet 有界清理：先回收任务工作区和旧归档，再清理终态数据库记录。
# 默认只预览；launchd 与磁盘守护必须显式传入 --apply。
set -euo pipefail

PARA_API_ROOT="${PARA_API_ROOT:-${HOME}/XCMAX-runtime/para-api/devfleet}"
PARA_RUNTIME_ROOT="${PARA_RUNTIME_ROOT:-$(cd "${PARA_API_ROOT}/.." && pwd)}"
PARA_NODE_BIN="${PARA_NODE_BIN:-${HOME}/.local/bin/node}"
PARA_CLEANUP_SCRIPT="${PARA_CLEANUP_SCRIPT:-${PARA_API_ROOT}/scripts/cleanup-expired-info.mjs}"
PARA_CLEANUP_ARCHIVE_DIR="${PARA_CLEANUP_ARCHIVE_DIR:-${PARA_API_ROOT}/api/data/cleanup-archives}"
PARA_LOG_DIR="${PARA_LOG_DIR:-${PARA_RUNTIME_ROOT}/logs}"
PARA_WORKSPACE_ROOT="${PARA_WORKSPACE_ROOT:-/tmp/devfleet-e2e/agent-workspace}"
PARA_CLEANUP_LOCK_DIR="${PARA_CLEANUP_LOCK_DIR:-${PARA_RUNTIME_ROOT}/para-cleanup.lock}"
PARA_DB_RETENTION_DAYS="${PARA_DB_RETENTION_DAYS:-30}"
PARA_LOG_RETENTION_DAYS="${PARA_LOG_RETENTION_DAYS:-7}"
PARA_WORKSPACE_RETENTION_MINUTES="${PARA_WORKSPACE_RETENTION_MINUTES:-120}"
PARA_CLEANUP_ARCHIVE_KEEP="${PARA_CLEANUP_ARCHIVE_KEEP:-2}"
PARA_MANUAL_DB_BACKUP_RETENTION_DAYS="${PARA_MANUAL_DB_BACKUP_RETENTION_DAYS:-14}"
PARA_MANUAL_DB_BACKUP_KEEP="${PARA_MANUAL_DB_BACKUP_KEEP:-2}"
XCMAX_WORKTREE_GC_ENABLED="${XCMAX_WORKTREE_GC_ENABLED:-1}"
XCMAX_REPO_ROOT="${XCMAX_REPO_ROOT:-${HOME}/Desktop/XCMAX}"
XCMAX_WORKTREE_ROOT="${XCMAX_WORKTREE_ROOT:-/private/tmp}"
XCMAX_WORKTREE_RETENTION_MINUTES="${XCMAX_WORKTREE_RETENTION_MINUTES:-360}"

APPLY=0
REASON="scheduled"
while (( $# > 0 )); do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --reason)
      [[ $# -ge 2 ]] || { printf '%s\n' "--reason requires a value" >&2; exit 2; }
      REASON="$2"
      shift 2
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[para-cleanup] %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

is_uint() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

require_uint() {
  local name="$1"
  local value="$2"
  if ! is_uint "${value}"; then
    log "${name} 必须是非负整数，当前为 ${value}"
    exit 2
  fi
}

safe_scoped_dir() {
  local target="${1%/}"
  local allowed_root="${2%/}"
  [[ -n "${target}" && -n "${allowed_root}" ]] || return 1
  [[ "${target}" != "/" && "${target}" != "${HOME%/}" ]] || return 1
  [[ "${target}" == "${allowed_root}/"* ]]
}

require_uint PARA_DB_RETENTION_DAYS "${PARA_DB_RETENTION_DAYS}"
require_uint PARA_LOG_RETENTION_DAYS "${PARA_LOG_RETENTION_DAYS}"
require_uint PARA_WORKSPACE_RETENTION_MINUTES "${PARA_WORKSPACE_RETENTION_MINUTES}"
require_uint PARA_CLEANUP_ARCHIVE_KEEP "${PARA_CLEANUP_ARCHIVE_KEEP}"
require_uint PARA_MANUAL_DB_BACKUP_RETENTION_DAYS "${PARA_MANUAL_DB_BACKUP_RETENTION_DAYS}"
require_uint PARA_MANUAL_DB_BACKUP_KEEP "${PARA_MANUAL_DB_BACKUP_KEEP}"
require_uint XCMAX_WORKTREE_GC_ENABLED "${XCMAX_WORKTREE_GC_ENABLED}"
require_uint XCMAX_WORKTREE_RETENTION_MINUTES "${XCMAX_WORKTREE_RETENTION_MINUTES}"

safe_scoped_dir "${PARA_CLEANUP_ARCHIVE_DIR}" "${PARA_API_ROOT}" || {
  log "拒绝不受限的归档目录: ${PARA_CLEANUP_ARCHIVE_DIR}"
  exit 2
}
safe_scoped_dir "${PARA_LOG_DIR}" "${PARA_RUNTIME_ROOT}" || {
  log "拒绝不受限的日志目录: ${PARA_LOG_DIR}"
  exit 2
}
[[ -n "${PARA_WORKSPACE_ROOT}" && "${PARA_WORKSPACE_ROOT}" != "/" && "${PARA_WORKSPACE_ROOT}" != "${HOME%/}" ]] || {
  log "拒绝不安全的工作区根: ${PARA_WORKSPACE_ROOT}"
  exit 2
}
[[ -n "${XCMAX_WORKTREE_ROOT}" && "${XCMAX_WORKTREE_ROOT}" != "/" && "${XCMAX_WORKTREE_ROOT}" != "${HOME%/}" ]] || {
  log "拒绝不安全的 Git 工作树根: ${XCMAX_WORKTREE_ROOT}"
  exit 2
}

acquire_lock() {
  if [[ -d "${PARA_CLEANUP_LOCK_DIR}" ]]; then
    local lock_pid
    lock_pid="$(cat "${PARA_CLEANUP_LOCK_DIR}/pid" 2>/dev/null || true)"
    if ! is_uint "${lock_pid}" || ! kill -0 "${lock_pid}" 2>/dev/null; then
      rm -f "${PARA_CLEANUP_LOCK_DIR}/pid" 2>/dev/null || true
      rmdir "${PARA_CLEANUP_LOCK_DIR}" 2>/dev/null || true
    fi
  fi
  if ! mkdir "${PARA_CLEANUP_LOCK_DIR}" 2>/dev/null; then
    log "已有清理任务运行，本轮跳过"
    exit 0
  fi
  printf '%s\n' "$$" > "${PARA_CLEANUP_LOCK_DIR}/pid"
}

release_lock() {
  rm -f "${PARA_CLEANUP_LOCK_DIR}/pid" 2>/dev/null || true
  rmdir "${PARA_CLEANUP_LOCK_DIR}" 2>/dev/null || true
}

prune_series() {
  local directory="$1"
  local pattern="$2"
  local keep="$3"
  local min_age_days="${4:-0}"
  local index=0
  local removed=0
  local file

  [[ -d "${directory}" ]] || return 0
  while IFS= read -r file; do
    [[ -n "${file}" ]] || continue
    if (( index < keep )); then
      index=$((index + 1))
      continue
    fi
    index=$((index + 1))
    if (( min_age_days > 0 )) && ! find "${file}" -prune -mtime "+${min_age_days}" -print | grep -q .; then
      continue
    fi
    if (( APPLY == 1 )); then
      rm -f "${file}"
    fi
    removed=$((removed + 1))
  done < <(find "${directory}" -maxdepth 1 -type f -name "${pattern}" -print | LC_ALL=C sort -r)
  log "归档策略 pattern=${pattern} keep=${keep} candidates=${removed} apply=${APPLY}"
}

cleanup_stale_workspaces() {
  local removed=0
  local directory
  local name
  [[ -d "${PARA_WORKSPACE_ROOT}" ]] || {
    log "任务工作区不存在，跳过: ${PARA_WORKSPACE_ROOT}"
    return 0
  }
  while IFS= read -r -d '' directory; do
    name="${directory##*/}"
    [[ "${name}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}- ]] || continue
    if (( APPLY == 1 )); then
      rm -rf "${directory}"
    fi
    removed=$((removed + 1))
  done < <(
    find "${PARA_WORKSPACE_ROOT}" -mindepth 1 -maxdepth 1 -type d \
      -mmin "+${PARA_WORKSPACE_RETENTION_MINUTES}" -print0
  )
  log "陈旧任务工作区 candidates=${removed} apply=${APPLY}"
}

cleanup_old_logs() {
  local removed=0
  local file
  [[ -d "${PARA_LOG_DIR}" ]] || {
    log "日志目录不存在，跳过: ${PARA_LOG_DIR}"
    return 0
  }
  while IFS= read -r -d '' file; do
    if (( APPLY == 1 )); then
      rm -f "${file}"
    fi
    removed=$((removed + 1))
  done < <(
    find "${PARA_LOG_DIR}" -type f -mtime "+${PARA_LOG_RETENTION_DAYS}" -print0
  )
  log "旧日志 candidates=${removed} retention_days=${PARA_LOG_RETENTION_DAYS} apply=${APPLY}"
}

cleanup_merged_worktrees() {
  local active_cwds
  local branch_head
  local removed=0
  local removed_kb=0
  local size_kb
  local worktree

  (( XCMAX_WORKTREE_GC_ENABLED == 1 )) || {
    log "Git 工作树回收已关闭"
    return 0
  }
  git -C "${XCMAX_REPO_ROOT}" rev-parse --git-dir >/dev/null 2>&1 || {
    log "XCMAX 仓库不可用，跳过 Git 工作树回收: ${XCMAX_REPO_ROOT}"
    return 0
  }
  git -C "${XCMAX_REPO_ROOT}" show-ref --verify --quiet refs/remotes/origin/main || {
    log "origin/main 不存在，跳过 Git 工作树回收"
    return 0
  }
  command -v lsof >/dev/null 2>&1 || {
    log "lsof 不可用，无法排除活动工作树，本轮不回收"
    return 0
  }
  if ! active_cwds="$(lsof -n -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"; then
    log "无法读取活动工作目录，本轮不回收 Git 工作树"
    return 0
  fi

  while IFS= read -r worktree; do
    [[ -n "${worktree}" && -d "${worktree}" ]] || continue
    [[ "${worktree}" == "${XCMAX_WORKTREE_ROOT%/}/"* ]] || continue
    [[ "${worktree}" != "${XCMAX_REPO_ROOT%/}" ]] || continue
    find "${worktree}" -prune -mmin "+${XCMAX_WORKTREE_RETENTION_MINUTES}" -print |
      grep -q . || continue
    case "${active_cwds}" in
      *"${worktree}"*) continue ;;
    esac
    [[ -z "$(git -C "${worktree}" status --porcelain 2>/dev/null)" ]] || continue
    branch_head="$(git -C "${worktree}" rev-parse HEAD 2>/dev/null || true)"
    [[ -n "${branch_head}" ]] || continue
    git -C "${XCMAX_REPO_ROOT}" merge-base --is-ancestor \
      "${branch_head}" refs/remotes/origin/main 2>/dev/null || continue
    size_kb="$(du -sk "${worktree}" 2>/dev/null | awk '{print $1}')"
    is_uint "${size_kb}" || size_kb=0
    if (( APPLY == 1 )); then
      git -C "${XCMAX_REPO_ROOT}" worktree remove "${worktree}"
    fi
    removed=$((removed + 1))
    removed_kb=$((removed_kb + size_kb))
  done < <(
    git -C "${XCMAX_REPO_ROOT}" worktree list --porcelain |
      sed -n 's/^worktree //p'
  )
  log "已合并干净工作树 candidates=${removed} reclaimable_kb=${removed_kb} apply=${APPLY}"
}

run_database_retention() {
  [[ -x "${PARA_NODE_BIN}" ]] || {
    log "Node 不可执行: ${PARA_NODE_BIN}"
    return 1
  }
  [[ -f "${PARA_CLEANUP_SCRIPT}" ]] || {
    log "数据库清理程序不存在: ${PARA_CLEANUP_SCRIPT}"
    return 1
  }
  local args=(
    "${PARA_CLEANUP_SCRIPT}"
    "--retention-days" "${PARA_DB_RETENTION_DAYS}"
    "--archive-dir" "${PARA_CLEANUP_ARCHIVE_DIR}"
    "--no-vacuum"
  )
  if (( APPLY == 1 )); then
    args+=("--apply")
  fi
  (
    cd "${PARA_API_ROOT}"
    "${PARA_NODE_BIN}" "${args[@]}"
  )
}

mkdir -p "${PARA_RUNTIME_ROOT}" "${PARA_CLEANUP_ARCHIVE_DIR}" "${PARA_LOG_DIR}"
acquire_lock
cleanup_on_exit() {
  local status=$?
  release_lock
  trap - EXIT
  exit "${status}"
}
trap cleanup_on_exit EXIT

log "开始 reason=${REASON} apply=${APPLY}"
cleanup_stale_workspaces
cleanup_old_logs
cleanup_merged_worktrees
# 先释放旧整库备份，避免在低磁盘时又因新备份触发 SQLITE_FULL。
prune_series "${PARA_CLEANUP_ARCHIVE_DIR}" "devfleet-*.db" "${PARA_CLEANUP_ARCHIVE_KEEP}"
prune_series "${PARA_CLEANUP_ARCHIVE_DIR}" "cleanup-*.json" "${PARA_CLEANUP_ARCHIVE_KEEP}"
prune_series \
  "${PARA_API_ROOT}/api/data" \
  "devfleet.db.pre-*" \
  "${PARA_MANUAL_DB_BACKUP_KEEP}" \
  "${PARA_MANUAL_DB_BACKUP_RETENTION_DAYS}"
run_database_retention
# 数据库清理成功后可能产生新备份，再次收敛到同一上限。
prune_series "${PARA_CLEANUP_ARCHIVE_DIR}" "devfleet-*.db" "${PARA_CLEANUP_ARCHIVE_KEEP}"
prune_series "${PARA_CLEANUP_ARCHIVE_DIR}" "cleanup-*.json" "${PARA_CLEANUP_ARCHIVE_KEEP}"
log "完成 reason=${REASON} apply=${APPLY}"
