#!/usr/bin/env bash
# Remote MODstore SRE operations for a single-server Docker Compose deployment.
set -euo pipefail

ACTION="${1:-help}"
REMOTE_REPO="${MODSTORE_REMOTE_REPO:-$(pwd)}"
BRANCH="${MODSTORE_REMOTE_BRANCH:-main}"
ROLLBACK_REF="${MODSTORE_ROLLBACK_REF:-}"
API_URL="${MODSTORE_API_URL:-http://127.0.0.1:8765}"
MARKET_URL="${MODSTORE_MARKET_URL:-http://127.0.0.1:4173}"
PAYMENT_URL="${MODSTORE_PAYMENT_URL:-http://127.0.0.1:8080}"
PROMETHEUS_URL="${MODSTORE_PROMETHEUS_URL:-http://127.0.0.1:9090}"
CHAOS_SCENARIO="${MODSTORE_CHAOS_SCENARIO:-payment-restart}"
K6_STAGE="${K6_STAGE:-smoke}"

log() {
  printf '[remote-sre] %s\n' "$*"
}

die() {
  printf '[remote-sre][err] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: remote_sre_ops.sh <action>

Actions:
  preflight       Check required commands, repo, .env, disk, and compose config.
  smoke           Run scripts/sre_smoke_check.py against local service URLs.
  backup          Run scripts/backup_modstore.py.
  deploy          git fetch/reset, backup, docker compose up --profile app, smoke.
  loadtest        Run compose loadtest profile with k6.
  chaos-dry-run   Print the selected chaos drill commands without executing faults.
  rollback        Reset to MODSTORE_ROLLBACK_REF, rebuild compose app stack, smoke.

Environment:
  MODSTORE_REMOTE_REPO       Remote repository path. Default: current directory.
  MODSTORE_REMOTE_BRANCH     Branch for deploy. Default: main.
  MODSTORE_ROLLBACK_REF      Required for rollback.
  MODSTORE_API_URL           Default: http://127.0.0.1:8765
  MODSTORE_MARKET_URL        Default: http://127.0.0.1:4173
  MODSTORE_PAYMENT_URL       Default: http://127.0.0.1:8080
  MODSTORE_PROMETHEUS_URL    Default: http://127.0.0.1:9090
  MODSTORE_CHAOS_SCENARIO    Default: payment-restart
  K6_STAGE                   Default: smoke
EOF
}

cd_deploy() {
  [ -d "$REMOTE_REPO" ] || die "repo not found: $REMOTE_REPO"
  cd "$REMOTE_REPO"
  if [ -d MODstore_deploy ]; then
    cd MODstore_deploy
  fi
  [ -f docker-compose.yml ] || die "docker-compose.yml not found in $(pwd)"
}

python_bin() {
  if [ -x .venv/bin/python ]; then
    printf '%s\n' ".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    die "python not found"
  fi
}

compose() {
  docker compose "$@"
}

require_compose_scheduler_running() {
  local running
  running=$(compose --profile app ps --status running --services 2>/dev/null || true)
  if ! printf '%s\n' "$running" | grep -qx 'scheduler'; then
    die "compose: service 'scheduler' is not running (workflow_scheduler / daily digest / outbox). Run: docker compose --profile app up -d scheduler. See docs/runbooks/remote-server-operations.md (section 后台任务)"
  fi
  log "compose scheduler: running"
}

preflight() {
  cd_deploy
  log "repo=$(pwd)"
  command -v git >/dev/null 2>&1 || die "git not found"
  command -v docker >/dev/null 2>&1 || die "docker not found"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin not available"
  command -v curl >/dev/null 2>&1 || die "curl not found"
  [ -f .env ] || log "warning: .env not found; compose defaults may be unsafe for production"
  compose --profile app --profile loadtest config >/dev/null
  log "compose config ok"
  log "disk:"
  df -h . || true
  log "docker:"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
}

smoke() {
  cd_deploy
  require_compose_scheduler_running
  local py
  py="$(python_bin)"
  "$py" scripts/sre_smoke_check.py \
    --base-url "$API_URL" \
    --market-url "$MARKET_URL" \
    --payment-url "$PAYMENT_URL" \
    --prometheus-url "$PROMETHEUS_URL"
}

backup() {
  cd_deploy
  local py
  py="$(python_bin)"
  "$py" scripts/backup_modstore.py
}

deploy() {
  cd_deploy
  preflight
  log "fetch/reset origin/${BRANCH}"
  git fetch origin "$BRANCH"
  git reset --hard "origin/${BRANCH}"
  backup
  log "build and start app stack"
  compose --profile app up -d --build
  smoke
}

loadtest() {
  cd_deploy
  K6_STAGE="$K6_STAGE" compose --profile app --profile loadtest run --rm loadtest
}

chaos_dry_run() {
  cd_deploy
  local py
  py="$(python_bin)"
  "$py" chaos/chaos_drill.py --scenario "$CHAOS_SCENARIO"
}

rollback() {
  [ -n "$ROLLBACK_REF" ] || die "set MODSTORE_ROLLBACK_REF before rollback"
  cd_deploy
  log "rollback to ${ROLLBACK_REF}"
  git fetch --all --tags
  git reset --hard "$ROLLBACK_REF"
  backup
  compose --profile app up -d --build
  smoke
}

case "$ACTION" in
  help|-h|--help) usage ;;
  preflight) preflight ;;
  smoke) smoke ;;
  backup) backup ;;
  deploy) deploy ;;
  loadtest) loadtest ;;
  chaos-dry-run) chaos_dry_run ;;
  rollback) rollback ;;
  *) usage; die "unknown action: $ACTION" ;;
esac
