#!/usr/bin/env bash
# Publish the exact production release payload to the restricted DR receiver.
# Called after a successful production deploy; component payloads may arrive
# independently and are verified/applied independently on DR.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

ENV_FILE="${OPS_ENV_FILE:-/etc/xcmax-ops.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

COMPONENT=""
SHA=""
while (($#)); do
  case "$1" in
    --component) COMPONENT="${2:-}"; shift 2 ;;
    --sha) SHA="${2:-}"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done
[[ "$COMPONENT" == "fhd" || "$COMPONENT" == "modstore" ]] || {
  echo "--component 必须为 fhd 或 modstore" >&2
  exit 2
}
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "--sha 必须是 40 位提交" >&2
  exit 2
}

TARGET="${OPS_BACKUP_SSH_TARGET:-}"
KEY="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
REMOTE_ROOT="${OPS_BACKUP_SSH_DEST:-.}"
SOURCE_ROOT="${OPS_XCMAX_ROOT:-/root/XCMAX}"
FHD_ARTIFACT_DIR="${OPS_FHD_ARTIFACT_DIR:-/var/www/update/releases/stable/server}"
MODSTORE_CURRENT="${OPS_MODSTORE_CURRENT:-/opt/xcmax/current}"
SPOOL="${OPS_RELEASE_SPOOL:-/var/backups/xcmax/releases}"
STATE="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG="${OPS_LOG_DIR:-/var/log/xcmax-ops}/release-sync.log"
LOCK="/run/lock/xcmax-release-sync-${COMPONENT}.lock"
TRANSFER_LOCK="${OPS_DR_TRANSFER_LOCK:-/run/lock/xcmax-dr-transfer.lock}"
TRANSFER_WAIT_SECONDS="${OPS_DR_TRANSFER_WAIT_SECONDS:-1800}"

[[ -n "$TARGET" && -f "$KEY" ]] || {
  echo "温备 SSH 目标或私钥未配置" >&2
  exit 1
}
install -d -m 0700 "$SPOOL" "$STATE" "$(dirname "$LOG")"
touch "$LOG"
exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

last_sha_file="$STATE/release_sync_${COMPONENT}_sha"
if [[ -f "$last_sha_file" && "$(cat "$last_sha_file")" == "$SHA" ]]; then
  exit 0
fi

staging="$SPOOL/.staging-${SHA}-${COMPONENT}-$$"
trap 'rm -rf -- "$staging"' EXIT
install -d -m 0700 "$staging"

if [[ "$COMPONENT" == "modstore" ]]; then
  git -C "$SOURCE_ROOT" cat-file -e "${SHA}^{commit}"
  active_sha="$(
    python3 - "$MODSTORE_CURRENT/.xcmax-release.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("git_sha", ""))
PY
  )"
  [[ "$active_sha" == "$SHA" ]] || {
    log "ERROR: MODstore 生产运行 SHA=$active_sha，拒绝同步请求 SHA=$SHA"
    exit 1
  }
  git -C "$SOURCE_ROOT" archive --format=tar.gz \
    --output="$staging/modstore-source.tar.gz" \
    "$SHA" -- "成都修茈科技有限公司"
  runtime_dist="$MODSTORE_CURRENT/成都修茈科技有限公司/MODstore_deploy/market/dist"
  [[ -f "$runtime_dist/index.html" ]] || {
    log "ERROR: MODstore 生产前端产物不存在: $runtime_dist/index.html"
    exit 1
  }
  tar -C "$(dirname "$runtime_dist")" -czf \
    "$staging/modstore-static.tar.gz" dist
  cp "$MODSTORE_CURRENT/.xcmax-release.json" "$staging/modstore-release.json"
  (
    cd "$staging"
    sha256sum \
      modstore-source.tar.gz modstore-static.tar.gz modstore-release.json \
      >modstore.MANIFEST.txt
  )
else
  manifest="$FHD_ARTIFACT_DIR/fhd-manifest.json"
  readarray -t manifest_values < <(
    python3 - "$manifest" <<'PY'
import json
import sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
print(doc.get("git_sha", ""))
print(doc.get("artifact", ""))
print(doc.get("deploy_mode", "tarball"))
PY
  )
  [[ "${manifest_values[0]:-}" == "$SHA" ]] || {
    log "ERROR: FHD manifest SHA=${manifest_values[0]:-missing}，拒绝同步 SHA=$SHA"
    exit 1
  }
  artifact="${manifest_values[1]:-}"
  [[ -n "$artifact" && -s "$FHD_ARTIFACT_DIR/$artifact" ]] || {
    log "ERROR: FHD 发布制品不存在: $artifact"
    exit 1
  }
  cp "$manifest" "$staging/fhd-manifest.json"
  cp "$FHD_ARTIFACT_DIR/$artifact" "$staging/$artifact"
  if [[ "${manifest_values[2]:-}" == "image" &&
    -s "$FHD_ARTIFACT_DIR/fhd-api-image.tar.gz" ]]; then
    cp "$FHD_ARTIFACT_DIR/fhd-api-image.tar.gz" "$staging/"
  fi
  (
    cd "$staging"
    find . -maxdepth 1 -type f ! -name 'fhd.MANIFEST.txt' -print0 |
      sort -z | xargs -0 sha256sum >fhd.MANIFEST.txt
  )
fi

printf '%s\n' "$SHA" >"$staging/${COMPONENT}.SHA"
date -u +%s >"$staging/${COMPONENT}.CREATED_AT"

(
  flock -w "$TRANSFER_WAIT_SECONDS" 8 || exit 1
  rsync -a --partial --delay-updates \
    -e "ssh -i $KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
    "$staging/" "${TARGET}:${REMOTE_ROOT}/runtime-releases/${SHA}/" \
    >>"$LOG" 2>&1
) 8>"$TRANSFER_LOCK"

printf '%s\n' "$SHA" >"$STATE/release_sync_${COMPONENT}_sha"
date -u +%s >"$STATE/release_sync_${COMPONENT}_last_success"
log "生产发布已同步到 DR: component=$COMPONENT sha=$SHA"
