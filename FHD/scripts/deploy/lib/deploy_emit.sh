# shellcheck shell=bash
# 轻量部署阶段日志（与 MODstore deploy_emit 字段对齐，避免强依赖姊妹栈路径）。

deploy_emit_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# deploy_emit <phase> <started|ok|failed|skipped> [message]
deploy_emit() {
  local phase="${1:?}"
  local status="${2:?}"
  local msg="${3:-}"
  local ts
  ts="$(deploy_emit_ts)"
  if [[ -n "$msg" ]]; then
    echo "[${ts}] phase=${phase} status=${status} msg=${msg}"
  else
    echo "[${ts}] phase=${phase} status=${status}"
  fi
  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    echo "::notice title=fhd-deploy::phase=${phase} status=${status}${msg:+ ${msg}}"
  fi
}
