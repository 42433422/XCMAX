#!/usr/bin/env bash
# 服务器 cron：读取 manifest，按 deploy_mode 路由 tarball 或 compose 应用。
# 替代 git_auto_update.sh（生产机不再 git pull）。
#
# 环境变量:
#   FHD_MANIFEST_PATH   默认 /var/www/update/releases/stable/server/fhd-manifest.json
#   FHD_ARTIFACT_DIR    默认与 manifest 同目录
#   FHD_DEPLOY_ROOT     默认 /opt/fhd-full
#   FHD_DEPLOY_MODE     覆盖 manifest deploy_mode（tarball|image）
#   FHD_SERVICE_NAME    传给 apply（staging: fhd-staging.service）
#   FHD_HEALTH_PORT     传给 apply（staging: 5101）
#   FHD_ENV_FILE        传给 compose apply（staging: /root/fhd-staging.env）
#   FHD_AUTO_UPDATE_LOCK  默认 /tmp/fhd-auto-update.lock（staging 须用独立锁）
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
APPLY_TARBALL="$SCRIPT_DIR/fhd-apply-release.sh"
APPLY_COMPOSE="$SCRIPT_DIR/fhd-apply-release-compose.sh"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"
if [[ -f "$SCRIPT_DIR/lib/dora_event.sh" ]]; then
  # shellcheck source=lib/dora_event.sh
  . "$SCRIPT_DIR/lib/dora_event.sh"
else
  dora_emit_deployment() {
    echo "DORA event helper is missing; deployment outcome was not persisted" >&2
    return 1
  }
fi

MANIFEST="${FHD_MANIFEST_PATH:-/var/www/update/releases/stable/server/fhd-manifest.json}"
ARTIFACT_DIR="${FHD_ARTIFACT_DIR:-$(dirname "$MANIFEST")}"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
LOCK="${FHD_AUTO_UPDATE_LOCK:-/tmp/fhd-auto-update.lock}"
LOCK_WAIT_SECONDS="${FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS:-0}"
FREEZE_MARKER="${FHD_MANIFEST_FREEZE_MARKER:-${MANIFEST}.frozen}"
AUTONOMY_DATA_DIR="${XCAGI_AUTONOMY_DATA_DIR:-/var/lib/xcagi/autonomy}"
AUTONOMY_PYTHON="${FHD_AUTONOMY_PYTHON:-$DEPLOY_ROOT/.venv/bin/python}"
if [[ ! -x "$AUTONOMY_PYTHON" ]]; then
  AUTONOMY_PYTHON="$(command -v python3)"
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

record_dora_deployment() {
  local status="$1"
  local environment="staging"
  [[ "${CHANNEL:-}" == "stable" ]] && environment="production"
  if ! dora_emit_deployment \
    "$status" \
    "${GIT_SHA:-}" \
    "${COMMIT_AT:-${BUILT_AT:-}}" \
    "$environment" \
    "${DEPLOY_MODE:-unknown}" \
    "${VERSION:-}" \
    "fhd-auto-update"; then
    log "ERROR: DORA 部署事件写入失败 status=$status sha=${GIT_SHA:-unknown}"
    return 1
  fi
}

authorize_production_release() {
  local channel="$1"
  local release_id="$2"
  if [[ "$channel" != "stable" ]]; then
    return 0
  fi
  install -d -m 700 "$AUTONOMY_DATA_DIR"
  local decision_json
  if ! decision_json="$(
    PYTHONPATH="$DEPLOY_ROOT" \
      XCAGI_AUTONOMY_DATA_DIR="$AUTONOMY_DATA_DIR" \
      "$AUTONOMY_PYTHON" - <<'PY' "$release_id"
import json
import sys

from app.domain.autonomy.autonomy_guard import evaluate_risk

release_id = sys.argv[1]
decision = evaluate_risk(
    "apply_release_to_cvm",
    {
        "trigger": "fhd_auto_update",
        "execution_mode": "automatic",
        "release_id": release_id,
    },
    action_id=f"release:{release_id}",
    source="fhd_auto_update.cron",
)
print(json.dumps(decision.to_dict(), ensure_ascii=False))
raise SystemExit(0 if decision.allowed else 42)
PY
  )"; then
    log "autonomy_guard 拒绝稳定通道发布 release=$release_id decision=${decision_json:-unavailable}"
    return 1
  fi
  log "autonomy_guard 已批准稳定通道发布 release=$release_id decision=$decision_json"
}

audit_production_release_outcome() {
  local channel="$1"
  local release_id="$2"
  local outcome="$3"
  if [[ "$channel" != "stable" ]]; then
    return 0
  fi
  PYTHONPATH="$DEPLOY_ROOT" \
    XCAGI_AUTONOMY_DATA_DIR="$AUTONOMY_DATA_DIR" \
    "$AUTONOMY_PYTHON" - <<'PY' "$release_id" "$outcome"
import sys

from app.domain.autonomy.audit_log import append_autonomy_audit

release_id, outcome = sys.argv[1:3]
append_autonomy_audit(
    {
        "action_id": f"release:{release_id}",
        "action": "apply_release_to_cvm",
        "risk_level": "HIGH",
        "decision": outcome,
        "approver": None,
        "outcome": outcome,
        "event_type": "action_outcome",
        "source": "fhd_auto_update.cron",
        "metadata": {"execution_mode": "automatic"},
    }
)
PY
}

sync_dr_release() {
  [[ "${CHANNEL:-}" == "stable" ]] || return 0
  local bundled_sync="$DEPLOY_ROOT/scripts/deploy/xcmax-release-sync.sh"
  local sync_script="${FHD_DR_SYNC_SCRIPT:-$bundled_sync}"
  if [[ ! -x "$sync_script" && -z "${FHD_DR_SYNC_SCRIPT:-}" ]]; then
    sync_script="/usr/local/xcmax-ops/dr/xcmax_release_sync.sh"
  fi
  if [[ ! -x "$sync_script" ]]; then
    log "ERROR: DR 发布同步脚本不可用: $sync_script"
    [[ "${FHD_DR_SYNC_STRICT:-1}" != "1" ]]
    return
  fi
  if "$sync_script" --component fhd --sha "$GIT_SHA"; then
    log "DR FHD 发布同步完成 sha=$GIT_SHA"
    return 0
  fi
  log "ERROR: DR FHD 发布同步失败 sha=$GIT_SHA"
  [[ "${FHD_DR_SYNC_STRICT:-1}" != "1" ]]
}

case "$LOCK_WAIT_SECONDS" in
  '' | *[!0-9]*)
    log "ERROR: FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS 必须为非负整数"
    exit 64
    ;;
esac

exec 9>"$LOCK"
if [[ "$LOCK_WAIT_SECONDS" -gt 0 ]]; then
  if ! flock -w "$LOCK_WAIT_SECONDS" 9; then
    log "等待另一更新实例超时 (${LOCK_WAIT_SECONDS}s)"
    exit 75
  fi
elif ! flock -n 9; then
  log "另一实例运行中，跳过"
  exit 0
fi

if [[ -f "$FREEZE_MARKER" ]]; then
  log "manifest 已冻结，跳过自动发布: $FREEZE_MARKER"
  exit 0
fi

if [[ ! -f "$MANIFEST" ]]; then
  log "manifest 不存在: $MANIFEST"
  exit 0
fi

IFS='|' read -r DEPLOY_MODE REMOTE_SHA ARTIFACT VERSION GIT_SHA IMAGE IMAGE_DIGEST CHANNEL ADMIN_CONSOLE_SHA256 BUILT_AT COMMIT_AT <<<"$(
  python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
values = [
    str(doc.get("deploy_mode", "tarball")),
    str(doc.get("sha256", "")),
    str(doc.get("artifact", "")),
    str(doc.get("version", "")),
    str(doc.get("git_sha", "")),
    str(doc.get("image", "")),
    str(doc.get("image_digest", "")),
    str(doc.get("channel", "")),
    str(doc.get("admin_console_sha256", "")),
    str(doc.get("built_at", "")),
    str(doc.get("commit_at", "")),
]
if any("|" in value or "\n" in value for value in values):
    raise SystemExit("manifest contains an invalid field delimiter")
print("|".join(values))
PY
)"

DEPLOY_MODE="${FHD_DEPLOY_MODE:-$DEPLOY_MODE}"
DEPLOY_MODE="${DEPLOY_MODE:-tarball}"
CHANNEL="${CHANNEL:-stable}"
[[ "$ADMIN_CONSOLE_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  log "ERROR: manifest 缺少管理端不可变资产身份"
  exit 1
}

if [[ "$DEPLOY_MODE" == "image" ]]; then
  if [[ -z "$IMAGE" || -z "$IMAGE_DIGEST" ]]; then
    log "ERROR: deploy_mode=image 但 manifest 缺少 image / image_digest"
    exit 1
  fi

  LOCAL_DIGEST=""
  if [[ -f "$DEPLOY_ROOT/.deploy-image-digest" ]]; then
    LOCAL_DIGEST="$(tr -d '[:space:]' < "$DEPLOY_ROOT/.deploy-image-digest")"
  fi

  if [[ "$IMAGE_DIGEST" == "$LOCAL_DIGEST" ]]; then
    log "已是最新（compose） version=$VERSION digest=${IMAGE_DIGEST:0:19}..."
    sync_dr_release
    exit 0
  fi

  if ! authorize_production_release "$CHANNEL" "${GIT_SHA:-$IMAGE_DIGEST}"; then
    exit 77
  fi

  log "发现新镜像 version=$VERSION sha=$GIT_SHA digest=${IMAGE_DIGEST:0:19}...，开始 compose 应用"
  APPLY_ENV=(
    "FHD_API_IMAGE=$IMAGE"
    "FHD_API_IMAGE_DIGEST=$IMAGE_DIGEST"
    "FHD_ARTIFACT_SHA256=$REMOTE_SHA"
    "FHD_ADMIN_CONSOLE_SHA256=$ADMIN_CONSOLE_SHA256"
    "FHD_GIT_SHA=$GIT_SHA"
    "FHD_DEPLOY_ROOT=$DEPLOY_ROOT"
    "FHD_ARTIFACT_DIR=$ARTIFACT_DIR"
  )
  [[ -n "${FHD_SERVICE_NAME:-}" ]] && APPLY_ENV+=("FHD_SERVICE_NAME=$FHD_SERVICE_NAME")
  [[ -n "${FHD_HEALTH_PORT:-}" ]] && APPLY_ENV+=("FHD_HEALTH_PORT=$FHD_HEALTH_PORT")
  [[ -n "${FHD_ENV_FILE:-}" ]] && APPLY_ENV+=("FHD_ENV_FILE=$FHD_ENV_FILE")
  if env "${APPLY_ENV[@]}" bash "$APPLY_COMPOSE"; then
    audit_production_release_outcome "$CHANNEL" "${GIT_SHA:-$IMAGE_DIGEST}" "executed"
    record_dora_deployment "success"
  else
    status=$?
    audit_production_release_outcome "$CHANNEL" "${GIT_SHA:-$IMAGE_DIGEST}" "execution_failed"
    record_dora_deployment "failed" || true
    exit "$status"
  fi
  sync_dr_release
  log "compose 自动更新完成 version=$VERSION"
  exit 0
fi

# --- tarball 模式（Phase 1 默认）---
if [[ -z "$REMOTE_SHA" || -z "$ARTIFACT" ]]; then
  log "manifest 字段不完整（tarball 模式需要 sha256 + artifact）"
  exit 1
fi

LOCAL_SHA=""
if [[ -f "$DEPLOY_ROOT/.deploy-sha256" ]]; then
  LOCAL_SHA="$(tr -d '[:space:]' < "$DEPLOY_ROOT/.deploy-sha256")"
fi

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  log "已是最新 version=$VERSION sha=$GIT_SHA"
  sync_dr_release
  exit 0
fi

if ! authorize_production_release "$CHANNEL" "${GIT_SHA:-$REMOTE_SHA}"; then
  exit 77
fi

TARBALL="$ARTIFACT_DIR/$ARTIFACT"
if [[ ! -f "$TARBALL" ]]; then
  log "ERROR: artifact 不存在: $TARBALL"
  exit 1
fi

LOCAL_FILE_SHA="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

if [[ "$LOCAL_FILE_SHA" != "$REMOTE_SHA" ]]; then
  log "ERROR: tarball sha256 与 manifest 不符 (file=$LOCAL_FILE_SHA manifest=$REMOTE_SHA)"
  exit 1
fi

log "发现新版本 version=$VERSION sha=$GIT_SHA，开始 tarball 应用"
APPLY_ENV=(
  "FHD_RELEASE_TARBALL=$TARBALL"
  "FHD_DEPLOY_ROOT=$DEPLOY_ROOT"
  "FHD_EXPECTED_SHA256=$REMOTE_SHA"
  "FHD_GIT_SHA=$GIT_SHA"
  "FHD_ADMIN_CONSOLE_SHA256=$ADMIN_CONSOLE_SHA256"
  "FHD_SKIP_PIP=${FHD_SKIP_PIP:-1}"
)
[[ -n "${FHD_SERVICE_NAME:-}" ]] && APPLY_ENV+=("FHD_SERVICE_NAME=$FHD_SERVICE_NAME")
[[ -n "${FHD_HEALTH_PORT:-}" ]] && APPLY_ENV+=("FHD_HEALTH_PORT=$FHD_HEALTH_PORT")
if env "${APPLY_ENV[@]}" bash "$APPLY_TARBALL"; then
  audit_production_release_outcome "$CHANNEL" "${GIT_SHA:-$REMOTE_SHA}" "executed"
  record_dora_deployment "success"
else
  status=$?
  audit_production_release_outcome "$CHANNEL" "${GIT_SHA:-$REMOTE_SHA}" "execution_failed"
  record_dora_deployment "failed" || true
  exit "$status"
fi
sync_dr_release
log "tarball 自动更新完成 version=$VERSION"
