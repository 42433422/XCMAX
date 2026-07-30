#!/bin/sh
set -eu
cd /app
# Schema SSOT: alembic is the only evolution path for DATABASE_URL-backed DBs.
# FHD_SKIP_ALEMBIC=1 is refused unless an explicit emergency override is set.
if [ "${FHD_SKIP_ALEMBIC:-0}" = "1" ]; then
  if [ "${FHD_ALLOW_SKIP_ALEMBIC_EMERGENCY:-0}" != "1" ]; then
    echo "FATAL: FHD_SKIP_ALEMBIC=1 is blocked. Alembic is the schema SSOT." >&2
    echo "Set FHD_ALLOW_SKIP_ALEMBIC_EMERGENCY=1 only for break-glass recovery." >&2
    exit 1
  fi
  echo "WARNING: FHD_SKIP_ALEMBIC=1 with emergency override — schema may drift." >&2
elif [ -n "${DATABASE_URL:-}" ]; then
  alembic -c alembic.ini upgrade head || exit 1
fi
if [ "${FHD_SKIP_ADMIN_BOOTSTRAP:-0}" != "1" ]; then
  python -c "from app.db.admin_init import create_admin_from_env; print(create_admin_from_env())" || true
fi
exec "$@"
