#!/usr/bin/env bash
# CI 窄包覆盖率门禁（与 test.yml backend-test 一致）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv-cov/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi
exec "$PY" -m pytest tests/ \
  --continue-on-collection-errors \
  --cov=app.neuro_bus --cov=app.middleware --cov=app.fastapi_routes \
  --cov=app.infrastructure.auth --cov=app.utils \
  --cov=app.utils.rate_limiter --cov=app.utils.password_hash --cov=app.config \
  --cov-report=term-missing \
  --cov-fail-under=70 \
  "$@"
