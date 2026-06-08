# shellcheck shell=bash
# 阶段化部署日志。人类可读行 + 可选单行 JSON（MODSTORE_DEPLOY_LOG_JSON=1）。
# 与 deploy-release-officer skill-deploy-pipeline 的 phase / 汇总字段方向对齐。

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
    echo "::notice title=deploy::phase=${phase} status=${status}${msg:+ ${msg}}"
  fi
  if [[ "${MODSTORE_DEPLOY_LOG_JSON:-}" == "1" ]]; then
    python3 -c "import json,sys; ts,phase,status,msg=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]; o={'ts':ts,'phase':phase,'status':status,'script':'${DEPLOY_SCRIPT_ID:-deploy}'}; \
      o.update({'message':msg} if msg else {}); print(json.dumps(o, ensure_ascii=False))" \
      "$ts" "$phase" "$status" "$msg"
  fi
}

# deploy_emit_summary_ok — 单行汇总 JSON（仅当 MODSTORE_DEPLOY_LOG_JSON=1）
deploy_emit_summary_json() {
  local build_ok="${1:-true}"
  local deploy_ok="${2:-true}"
  local smoke_ok="${3:-true}"
  local rollback="${4:-false}"
  [[ "${MODSTORE_DEPLOY_LOG_JSON:-}" == "1" ]] || return 0
  MODSTORE_BUILD_OK="$build_ok" MODSTORE_DEPLOY_OK="$deploy_ok" MODSTORE_SMOKE_OK="$smoke_ok" MODSTORE_ROLLBACK="$rollback" python3 <<'PY'
import json
import os

def B(x: str) -> bool:
    return str(x).strip().lower() in ("1", "true", "yes")

print(
    json.dumps(
        {
            "status": "ok",
            "build_ok": B(os.environ.get("MODSTORE_BUILD_OK", "false")),
            "deploy_ok": B(os.environ.get("MODSTORE_DEPLOY_OK", "false")),
            "smoke_ok": B(os.environ.get("MODSTORE_SMOKE_OK", "false")),
            "rollback_needed": B(os.environ.get("MODSTORE_ROLLBACK", "false")),
        },
        ensure_ascii=False,
    )
)
PY
}
