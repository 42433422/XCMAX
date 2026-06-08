#!/usr/bin/env bash
# 重建 api + scheduler 镜像并拉起，随后做最小冒烟（health、容器内 git、摘要用分支/提交）。
# 用法（在服务器 MODstore_deploy 目录）：
#   chmod +x scripts/rebuild_api_scheduler.sh && ./scripts/rebuild_api_scheduler.sh
#
# 若部署目录本身不是 git 根（常见：仓库在父目录），可指定：
#   MODSTORE_GIT_BASE=/root/modstore-git ./scripts/rebuild_api_scheduler.sh
#
# 若无 git 或无需推导，可在 .env 中写好 MODSTORE_GIT_BRANCH / MODSTORE_GIT_COMMIT（或 MODSTORE_GIT_SHA）。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GIT_BASE="${MODSTORE_GIT_BASE:-}"
if [ -z "$GIT_BASE" ]; then
  if [ -d "$ROOT/.git" ]; then
    GIT_BASE="$ROOT"
  elif [ -d "$ROOT/../.git" ]; then
    GIT_BASE="$(cd "$ROOT/.." && pwd)"
  else
    GIT_BASE="$ROOT"
  fi
fi

BR="${MODSTORE_GIT_BRANCH:-}"
SHA="${MODSTORE_GIT_COMMIT:-}"
if [ -z "$BR" ] && git -C "$GIT_BASE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BR="$(git -C "$GIT_BASE" rev-parse --abbrev-ref HEAD)"
fi
if [ -z "$SHA" ] && git -C "$GIT_BASE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  SHA="$(git -C "$GIT_BASE" rev-parse HEAD)"
fi

export MODSTORE_GIT_BRANCH="${MODSTORE_GIT_BRANCH:-$BR}"
export MODSTORE_GIT_COMMIT="${MODSTORE_GIT_COMMIT:-$SHA}"

echo "[rebuild] GIT_BASE=$GIT_BASE"
echo "[rebuild] MODSTORE_GIT_BRANCH=${MODSTORE_GIT_BRANCH:-<empty>}"
COMMIT_DISP="${MODSTORE_GIT_COMMIT:-<empty>}"
echo "[rebuild] MODSTORE_GIT_COMMIT=${COMMIT_DISP:0:64}"
echo ""

docker compose --profile app build api scheduler
docker compose --profile app up -d api scheduler

API_PORT="${MODSTORE_API_PORT:-8765}"
echo "--- GET /api/health (port $API_PORT) — 等待 api 就绪（最多约 45s）"
HEALTH_OK=0
for i in {1..15}; do
  if curl -fsS --max-time 5 "http://127.0.0.1:${API_PORT}/api/health" -o /tmp/modstore_health.json 2>/dev/null; then
    head -c 600 /tmp/modstore_health.json
    echo ""
    HEALTH_OK=1
    rm -f /tmp/modstore_health.json
    break
  fi
  echo "(health retry $i/15, sleep 3s)"
  sleep 3
done
if [ "$HEALTH_OK" != 1 ]; then
  echo "warning: /api/health 未在重试窗内就绪，请手动 curl"
fi
echo ""
echo "--- git --version (scheduler)"
docker exec modstore_deploy-scheduler-1 git --version
echo "--- daily_digest _digest_git_branch_and_head(/app)"
docker exec modstore_deploy-scheduler-1 python -c \
  'from pathlib import Path; from modstore_server.daily_digest import _digest_git_branch_and_head; print(_digest_git_branch_and_head(Path("/app")))'

echo "--- optional: daily digest SMTP (仅验证跑通，勿频繁执行)"
echo "docker exec modstore_deploy-scheduler-1 python -c 'import logging; logging.basicConfig(level=logging.INFO); from modstore_server.daily_digest import run_daily_digest_email; run_daily_digest_email()'"
