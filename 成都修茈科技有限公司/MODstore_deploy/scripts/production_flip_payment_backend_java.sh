#!/usr/bin/env bash
# 生产直切 PAYMENT_BACKEND=java（见 docs/PAYMENT_GRAY_RELEASE.md §3）
# 用法：
#   cd MODstore_deploy
#   ./scripts/production_flip_payment_backend_java.sh preflight   # 仅检查
#   ./scripts/production_flip_payment_backend_java.sh flip        # 改 .env 并重启 api
#   ./scripts/production_flip_payment_backend_java.sh rollback  # 回滚为 python
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${MODSTORE_ENV_FILE:-$ROOT/.env}"
COMPOSE="docker compose --profile app"
ACTION="${1:-preflight}"

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

backup_env() {
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  cp "$ENV_FILE" "${ENV_FILE}.bak.${ts}"
  echo "Backed up $ENV_FILE -> ${ENV_FILE}.bak.${ts}"
}

set_payment_backend() {
  local val="$1"
  if grep -q '^PAYMENT_BACKEND=' "$ENV_FILE" 2>/dev/null; then
    if [[ "$(uname)" == Darwin ]]; then
      sed -i '' "s/^PAYMENT_BACKEND=.*/PAYMENT_BACKEND=${val}/" "$ENV_FILE"
    else
      sed -i "s/^PAYMENT_BACKEND=.*/PAYMENT_BACKEND=${val}/" "$ENV_FILE"
    fi
  else
    echo "PAYMENT_BACKEND=${val}" >>"$ENV_FILE"
  fi
}

preflight() {
  load_env
  echo "==> Ensuring payment-service is up"
  $COMPOSE up -d payment-service
  echo "==> Java actuator health"
  curl -fsS "http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080}/actuator/health" | head -c 500
  echo ""
  echo "==> Gray release check (Java direct)"
  python3 scripts/payment_gray_release_check.py \
    --base-url "http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080}"
  echo "==> Payment health via FastAPI (current backend=${PAYMENT_BACKEND:-python})"
  curl -fsS "http://127.0.0.1:${MODSTORE_API_PORT:-8765}/api/health/payment" || true
  echo ""
}

flip() {
  load_env
  if [[ "${PAYMENT_BACKEND:-python}" == "java" ]]; then
    echo "PAYMENT_BACKEND already java"
    exit 0
  fi
  backup_env
  echo "==> Drain window: wait for in-flight Python orders (default 60s, override DRAIN_SECONDS)"
  sleep "${DRAIN_SECONDS:-60}"
  set_payment_backend java
  echo "==> Restart api only"
  $COMPOSE up -d --no-deps api
  sleep 5
  preflight
  echo "==> Contract alignment (post-flip)"
  python3 scripts/payment_gray_release_check.py \
    --base-url "http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080}" \
    --payment-backend java
  echo "==> SRE smoke"
  python3 scripts/sre_smoke_check.py \
    --base-url "http://127.0.0.1:${MODSTORE_API_PORT:-8765}" \
    --payment-url "http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080}" \
    --market-url "http://127.0.0.1:${MODSTORE_MARKET_PORT:-4173}" || true
  echo "Flip complete. Verify https://xiu-ci.com/api/payment/plans and a test checkout."
}

rollback() {
  backup_env
  set_payment_backend python
  $COMPOSE up -d --no-deps api
  echo "Rolled back to PAYMENT_BACKEND=python. Restore ALIPAY notify upstream if changed."
}

case "$ACTION" in
  preflight) preflight ;;
  flip) flip ;;
  rollback) rollback ;;
  *)
    echo "Usage: $0 {preflight|flip|rollback}"
    exit 1
    ;;
esac
