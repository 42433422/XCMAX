#!/bin/sh
set -eu
cd /app
if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required; refusing to start without the Alembic schema gate." >&2
  exit 78
fi
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current --check-heads
if [ "${FHD_SKIP_ADMIN_BOOTSTRAP:-0}" != "1" ]; then
  python -c "from app.db.admin_init import create_admin_from_env; print(create_admin_from_env())" || true
fi
exec "$@"
