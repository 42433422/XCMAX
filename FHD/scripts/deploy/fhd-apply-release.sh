#!/usr/bin/env bash
# 服务器端：解压 FHD 发布包 → pip（如需）→ restart fhd-full → 健康检查。
# 由 fhd-push-release.sh / fhd-auto-update.sh / CI 调用。
#
# 环境变量:
#   FHD_DEPLOY_ROOT      默认 /opt/fhd-full
#   FHD_RELEASE_TARBALL  必填（除非 FHD_MANIFEST_DIR 已含 artifact）
#   FHD_SERVICE_NAME     默认 fhd-full.service
#   FHD_HEALTH_PORT      默认 5100
#   FHD_RUN_MIGRATIONS   1 时执行 alembic upgrade head
#   FHD_SKIP_PIP         1 跳过 pip install
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
if [[ -f "$SCRIPT_DIR/lib/deploy_emit.sh" ]]; then
  # shellcheck source=lib/deploy_emit.sh
  . "$SCRIPT_DIR/lib/deploy_emit.sh"
else
  deploy_emit() { echo "[deploy] $*"; }
fi
export DEPLOY_SCRIPT_ID="fhd_apply_release"

DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
SERVICE="${FHD_SERVICE_NAME:-fhd-full.service}"
HEALTH_PORT="${FHD_HEALTH_PORT:-5100}"
VENV="${FHD_VENV:-$DEPLOY_ROOT/.venv}"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

TARBALL="${FHD_RELEASE_TARBALL:-}"
if [[ -z "$TARBALL" || ! -f "$TARBALL" ]]; then
  log "ERROR: FHD_RELEASE_TARBALL 不存在: ${TARBALL:-<empty>}"
  deploy_emit apply failed "missing_tarball"
  exit 1
fi

TARBALL_SHA256="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

EXPECTED_SHA="${FHD_EXPECTED_SHA256:-}"
if [[ -n "$EXPECTED_SHA" && "$TARBALL_SHA256" != "$EXPECTED_SHA" ]]; then
  log "ERROR: tarball sha256 与期望不符 (file=$TARBALL_SHA256 expected=$EXPECTED_SHA)"
  deploy_emit apply failed "sha256_mismatch"
  exit 1
fi

deploy_emit apply started "tarball=$TARBALL"
log "开始应用发布包: $TARBALL sha256=${TARBALL_SHA256:0:16}..."

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="${FHD_BACKUP_ROOT:-/opt/fhd-full-backups}"
mkdir -p "$BACKUP_ROOT"
BACKUP="$BACKUP_ROOT/pre-$TS"
mkdir -p "$BACKUP"

for item in app XCAGI alembic alembic.ini mods xcagi_common resources requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$DEPLOY_ROOT/$item" ]]; then
    rsync -a "$DEPLOY_ROOT/$item" "$BACKUP/"
  fi
done
if [[ -f "$DEPLOY_ROOT/.deploy-last.tar.gz" ]]; then
  cp "$DEPLOY_ROOT/.deploy-last.tar.gz" "$BACKUP/.deploy-last.tar.gz"
fi
log "已备份至 $BACKUP"

rollback_from_backup() {
  log "执行回滚: $BACKUP"
  for item in app XCAGI alembic alembic.ini mods xcagi_common resources requirements-base.txt requirements.txt pyproject.toml; do
    if [[ -e "$BACKUP/$item" ]]; then
      rsync -a --delete "$BACKUP/$item" "$DEPLOY_ROOT/"
    fi
  done
  systemctl restart "$SERVICE" || true
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/fhd-apply.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$TARBALL" -C "$TMP"

for item in app XCAGI alembic alembic.ini mods xcagi_common resources requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$TMP/$item" ]]; then
    rsync -a --delete "$TMP/$item" "$DEPLOY_ROOT/"
  fi
done
if [[ -d "$TMP/scripts/deploy" ]]; then
  mkdir -p "$DEPLOY_ROOT/scripts"
  rsync -a --delete "$TMP/scripts/deploy/" "$DEPLOY_ROOT/scripts/deploy/"
fi
if [[ -d "$TMP/docker" ]]; then
  mkdir -p "$DEPLOY_ROOT/docker"
  rsync -a "$TMP/docker/" "$DEPLOY_ROOT/docker/"
fi
log "代码已同步至 $DEPLOY_ROOT"

if [[ "${FHD_SKIP_PIP:-0}" != "1" ]]; then
  deploy_emit pip started
  if [[ ! -x "$VENV/bin/pip" ]]; then
    python3 -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  . "$VENV/bin/activate"
  pip install -q -U pip
  if [[ -f "$DEPLOY_ROOT/requirements-base.txt" ]]; then
    pip install -q -r "$DEPLOY_ROOT/requirements-base.txt"
  elif [[ -f "$DEPLOY_ROOT/requirements.txt" ]]; then
    pip install -q -r "$DEPLOY_ROOT/requirements.txt"
  fi
  deploy_emit pip ok
fi

if [[ "${FHD_RUN_MIGRATIONS:-0}" == "1" && -f "$DEPLOY_ROOT/alembic.ini" ]]; then
  deploy_emit migrate started
  # shellcheck disable=SC1091
  . "$VENV/bin/activate"
  (cd "$DEPLOY_ROOT" && alembic upgrade head) || {
    log "WARN: alembic upgrade 失败，请人工检查"
    deploy_emit migrate failed
  }
  deploy_emit migrate ok
fi

deploy_emit restart started "service=$SERVICE"
systemctl restart "$SERVICE"
sleep "${FHD_HEALTH_INITIAL_SLEEP:-15}"

API_CODE=000
HEALTH_PATH="${FHD_HEALTH_PATH:-/api/health}"
HEALTH_RETRIES="${FHD_HEALTH_RETRIES:-90}"
HEALTH_INTERVAL="${FHD_HEALTH_INTERVAL:-3}"
for _ in $(seq 1 "$HEALTH_RETRIES"); do
  c="$(curl -sS -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:${HEALTH_PORT}${HEALTH_PATH}" 2>/dev/null || true)"
  c="${c:-000}"
  if [[ "$c" == "200" ]]; then
    API_CODE=200
    break
  fi
  sleep "$HEALTH_INTERVAL"
done

if [[ "$API_CODE" != "200" ]]; then
  log "ERROR: /api/health 未就绪 (code=$API_CODE)，尝试回滚"
  rollback_from_backup
  deploy_emit apply failed "health_check rollback"
  exit 1
fi

echo "$TARBALL_SHA256" > "$DEPLOY_ROOT/.deploy-sha256"
cp "$TARBALL" "${DEPLOY_ROOT}/.deploy-last.tar.gz" 2>/dev/null || true

log "发布成功 health=200 sha256=${TARBALL_SHA256:0:16}..."
deploy_emit apply ok "port=$HEALTH_PORT"
