#!/usr/bin/env bash
# 严格 mypy 门禁：仅覆盖核心域/认证/限流（全仓 app.* 仍分阶段收口）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "== mypy strict gate =="
mypy \
  app/infrastructure/auth \
  app/application/auth_app_service.py \
  app/utils/deployment.py \
  app/utils/rate_limiter.py \
  --no-error-summary
