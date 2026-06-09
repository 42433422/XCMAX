#!/usr/bin/env bash
# 服务器端：按 manifest 镜像 digest 执行 docker compose pull/up → 健康检查 → 失败回滚。
#
# 环境变量:
#   FHD_DEPLOY_ROOT        默认 /opt/fhd-full
#   FHD_COMPOSE_FILE       默认 $DEPLOY_ROOT/docker/docker-compose.fhd-prod.yml
#   FHD_API_IMAGE          镜像仓库（无 digest）
#   FHD_API_IMAGE_DIGEST   sha256:...
#   FHD_HEALTH_PORT        默认 5100
#   FHD_ENV_FILE           默认 /root/fhd-full.env
#   FHD_USE_BUNDLED_REDIS  1 时加 --profile bundled-redis
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
if [[ -f "$SCRIPT_DIR/lib/deploy_emit.sh" ]]; then
  # shellcheck source=lib/deploy_emit.sh
  . "$SCRIPT_DIR/lib/deploy_emit.sh"
else
  deploy_emit() { echo "[deploy] $*"; }
fi
export DEPLOY_SCRIPT_ID="fhd_apply_release_compose"

DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
COMPOSE_FILE="${FHD_COMPOSE_FILE:-$DEPLOY_ROOT/docker/docker-compose.fhd-prod.yml}"
HEALTH_PORT="${FHD_HEALTH_PORT:-5100}"
ENV_FILE="${FHD_ENV_FILE:-/root/fhd-full.env}"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

if ! command -v docker >/dev/null 2>&1; then
  log "ERROR: 未安装 docker，无法 compose 部署"
  deploy_emit apply failed "docker_missing"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  log "ERROR: 需要 Docker Compose v2（docker compose）"
  deploy_emit apply failed "compose_v2_missing"
  exit 1
fi

IMAGE="${FHD_API_IMAGE:-}"
DIGEST="${FHD_API_IMAGE_DIGEST:-}"
if [[ -z "$IMAGE" || -z "$DIGEST" ]]; then
  log "ERROR: FHD_API_IMAGE / FHD_API_IMAGE_DIGEST 未设置"
  deploy_emit apply failed "missing_image"
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  log "ERROR: compose 文件不存在: $COMPOSE_FILE"
  deploy_emit apply failed "missing_compose"
  exit 1
fi

PREV_DIGEST=""
if [[ -f "$DEPLOY_ROOT/.deploy-image-digest" ]]; then
  PREV_DIGEST="$(tr -d '[:space:]' < "$DEPLOY_ROOT/.deploy-image-digest")"
fi

deploy_emit apply started "image=${IMAGE} digest=${DIGEST:0:19}..."
log "开始 compose 发布 image=$IMAGE digest=${DIGEST:0:19}..."

export FHD_API_IMAGE="$IMAGE"
export FHD_API_IMAGE_DIGEST="$DIGEST"
export FHD_API_IMAGE_REF="${IMAGE}@${DIGEST}"
export FHD_DEPLOY_ROOT="$DEPLOY_ROOT"
export FHD_ENV_FILE="$ENV_FILE"

COMPOSE_OPTS=(-f "$COMPOSE_FILE")
if [[ "${FHD_USE_BUNDLED_REDIS:-0}" == "1" ]]; then
  COMPOSE_OPTS+=(--profile bundled-redis)
fi

rollback_compose() {
  local digest="$1"
  if [[ -z "$digest" ]]; then
    log "WARN: 无上一 digest，跳过 compose 回滚"
    return 1
  fi
  log "compose 回滚至 digest=${digest:0:19}..."
  export FHD_API_IMAGE_DIGEST="$digest"
  export FHD_API_IMAGE_REF="${FHD_API_IMAGE}@${digest}"
  docker compose "${COMPOSE_OPTS[@]}" pull fhd-api || true
  docker compose "${COMPOSE_OPTS[@]}" up -d --pull never fhd-api || true
}

deploy_emit pull started
PULL_OK=0
if docker compose "${COMPOSE_OPTS[@]}" pull fhd-api; then
  PULL_OK=1
elif docker image inspect "${IMAGE}@${DIGEST}" >/dev/null 2>&1; then
  log "WARN: pull 失败但本地已有 digest，继续 up"
  PULL_OK=1
fi
if [[ "$PULL_OK" != "1" ]]; then
  log "ERROR: docker compose pull 失败且无本地 digest"
  deploy_emit pull failed
  rollback_compose "$PREV_DIGEST"
  deploy_emit apply failed "pull_failed"
  exit 1
fi
deploy_emit pull ok

deploy_emit up started
if ! docker compose "${COMPOSE_OPTS[@]}" up -d --pull never fhd-api; then
  log "ERROR: docker compose up 失败"
  deploy_emit up failed
  rollback_compose "$PREV_DIGEST"
  deploy_emit apply failed "up_failed"
  exit 1
fi
deploy_emit up ok

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
  log "ERROR: /api/health 未就绪 (code=$API_CODE)，尝试 compose 回滚"
  rollback_compose "$PREV_DIGEST"
  deploy_emit apply failed "health_check rollback"
  exit 1
fi

echo "$DIGEST" > "$DEPLOY_ROOT/.deploy-image-digest"

log "compose 发布成功 health=200 digest=${DIGEST:0:19}..."
deploy_emit apply ok "port=$HEALTH_PORT mode=compose"
