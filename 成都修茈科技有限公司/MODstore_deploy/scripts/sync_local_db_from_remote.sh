#!/usr/bin/env bash
# 将远程 PostgreSQL 恢复到本地（需 pg_dump / pg_restore）。
# 用法：
#   chmod +x scripts/sync_local_db_from_remote.sh
#   export REMOTE_DATABASE_URL='postgresql://user:pass@host:5432/modstore'
#   ./scripts/sync_local_db_from_remote.sh
#
# 可选：LOCAL_DATABASE_URL（默认 postgresql://modstore:modstore@127.0.0.1:5432/modstore）

set -euo pipefail

REMOTE_URL="${REMOTE_DATABASE_URL:?请先 export REMOTE_DATABASE_URL}"
LOCAL_URL="${LOCAL_DATABASE_URL:-postgresql://modstore:modstore@127.0.0.1:5432/modstore}"

DUMP="$(mktemp /tmp/modstore_sync_XXXXXX.dump)"
trap 'rm -f "$DUMP"' EXIT

echo "==> pg_dump 远程 -> $DUMP"
pg_dump --dbname="$REMOTE_URL" --format=custom --file="$DUMP" --no-owner

echo "==> 即将 pg_restore 到本地: $LOCAL_URL"
read -r -p "确认覆盖本地数据库? [y/N] " ok
if [[ ! "$ok" =~ ^[yY]$ ]]; then
  echo "已取消"; exit 1
fi

pg_restore --dbname="$LOCAL_URL" --clean --if-exists --no-owner --no-acl --verbose "$DUMP" || true

echo ""
echo "完成。请在 .env.local 设置 DATABASE_URL=$LOCAL_URL ，并注释 MODSTORE_DB_PATH。"
