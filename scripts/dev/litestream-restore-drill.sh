#!/usr/bin/env bash
# Litestream 恢复演练（阶段 10 · 灾难恢复）
#
# 从对象存储恢复指定数据库到临时目录，做完整性校验并测量 RTO（恢复耗时）。
# 不触碰生产数据；可定期由 CI / cron 执行作为「演练」。
#
# 用法：
#   LITESTREAM_REPLICA_URL=s3://xcagi-primary/<host> \
#   ./scripts/dev/litestream-restore-drill.sh orders.db
#
#   # 从异地 DR 区域演练：
#   REPLICA=dr LITESTREAM_REPLICA_URL_DR=s3://xcagi-dr/<host> \
#   ./scripts/dev/litestream-restore-drill.sh orders.db
set -euo pipefail

DB_NAME="${1:-orders.db}"
REPLICA="${REPLICA:-primary}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v litestream >/dev/null 2>&1; then
  echo "litestream 未安装。macOS: brew install litestream" >&2
  exit 1
fi

# 选择恢复来源 URL
if [[ "$REPLICA" == "dr" ]]; then
  SRC_URL="${LITESTREAM_REPLICA_URL_DR:?需设置 LITESTREAM_REPLICA_URL_DR}"
else
  SRC_URL="${LITESTREAM_REPLICA_URL:?需设置 LITESTREAM_REPLICA_URL}"
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
RESTORED="$WORKDIR/${DB_NAME}"

echo "[drill] 从 replica=$REPLICA url=$SRC_URL 恢复 $DB_NAME ..."
START=$(date +%s)
litestream restore -o "$RESTORED" "${SRC_URL}/${DB_NAME}"
END=$(date +%s)
RTO=$((END - START))

if [[ ! -f "$RESTORED" ]]; then
  echo "[drill] 失败：未生成恢复文件" >&2
  exit 2
fi

# 完整性校验
INTEGRITY="$(sqlite3 "$RESTORED" 'PRAGMA integrity_check;' || echo 'failed')"
TABLES="$(sqlite3 "$RESTORED" "SELECT count(*) FROM sqlite_master WHERE type='table';" || echo '0')"
SIZE="$(du -h "$RESTORED" | cut -f1)"

echo "----------------------------------------"
echo "[drill] 数据库      : $DB_NAME"
echo "[drill] 来源副本    : $REPLICA"
echo "[drill] RTO(恢复耗时): ${RTO}s"
echo "[drill] 大小        : $SIZE"
echo "[drill] 表数量      : $TABLES"
echo "[drill] 完整性      : $INTEGRITY"
echo "----------------------------------------"

if [[ "$INTEGRITY" != "ok" ]]; then
  echo "[drill] ❌ 完整性校验未通过" >&2
  exit 3
fi
echo "[drill] ✅ 恢复演练通过"
