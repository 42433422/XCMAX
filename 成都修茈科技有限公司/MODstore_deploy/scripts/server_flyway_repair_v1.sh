#!/bin/bash
# Run ON SERVER. Fixes Flyway V1 checksum when local JAR has different V1__*.sql than DB.
# Get NEW_CHECKSUM from modstore-payment log line: "Resolved locally : <n>"
# Prefer future deploy: rsync java 时排除 --exclude=src/main/resources/db/migration/ 再单独对齐迁移。
set -euo pipefail
ENV_FILE="${1:-/root/成都修茈科技有限公司/MODstore_deploy/.env}"
NEW_CHECKSUM="${2:--1040244037}"
source "$ENV_FILE"
export PGPASSWORD="$DATABASE_PASSWORD"
psql -h 127.0.0.1 -U "$DATABASE_USER" -d payment_db -c "UPDATE flyway_schema_history SET checksum = ${NEW_CHECKSUM} WHERE version = '1';"
echo "OK: V1 checksum -> ${NEW_CHECKSUM}. Then: systemctl restart modstore-payment"
