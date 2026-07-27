#!/usr/bin/env bash
# Install DR-side scripts and schedules. Run from an exact checked-out release.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
CRON_FILE="/etc/cron.d/xcmax-dr"

declare -A scripts=(
  [xcmax_dr_finalize.sh]=xcmax-dr-finalize
  [xcmax_dr_restore_latest.sh]=xcmax-dr-restore-latest
  [xcmax_dr_prepare_runtime.sh]=xcmax-dr-prepare-runtime
  [xcmax_wal_prepare_standby.sh]=xcmax-dr-prepare-standby
  [xcmax_wal_prepare_standby_pg16.sh]=xcmax-dr-prepare-standby-pg16
  [xcmax_dr_apply_release.sh]=xcmax-dr-apply-release
  [xcmax_dr_prepare_edge.sh]=xcmax-dr-prepare-edge
  [xcmax_dr_promote.sh]=xcmax-dr-promote
  [xcmax_dr_status.sh]=xcmax-dr-status
)

for source in "${!scripts[@]}"; do
  [[ -f "$SRC_DIR/$source" ]] || {
    echo "缺少 DR 脚本: $source" >&2
    exit 1
  }
  install -m 0755 "$SRC_DIR/$source" "/usr/local/sbin/${scripts[$source]}"
done

cat >"$CRON_FILE" <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=Asia/Shanghai

# 校验 daily logical dump 并封存为接收账号不可改写的 root 归档。
*/10 * * * * root /usr/local/sbin/xcmax-dr-finalize >/dev/null 2>&1
# 逻辑恢复链保留为跨版本回退路径。
7,22,37,52 * * * * root /usr/local/sbin/xcmax-dr-restore-latest >/dev/null 2>&1
# 每个生产发布的精确 SHA 到达后校验并原子切换 DR 代码。
2,12,22,32,42,52 * * * * root /usr/local/sbin/xcmax-dr-apply-release >/dev/null 2>&1
# 新物理基础备份到达后重建 PG10 standby；平时立即退出。
17 * * * * root /usr/local/sbin/xcmax-dr-prepare-standby >/dev/null 2>&1
# 新物理基础备份到达后重建 PG16 application standby。
27 * * * * root /usr/local/sbin/xcmax-dr-prepare-standby-pg16 >/dev/null 2>&1
EOF
chmod 0644 "$CRON_FILE"
install -d -m 0700 /var/lib/xcmax-dr /var/log/xcmax-dr
install -d -m 0700 /srv/xcmax-dr/incoming
for incoming_dir in \
  wal wal/base wal/archive wal/status \
  wal-pg16 wal-pg16/base wal-pg16/archive wal-pg16/status \
  runtime-releases; do
  install -d -o xcmaxdr -g xcmaxdr -m 0700 \
    "/srv/xcmax-dr/incoming/$incoming_dir"
done
if [[ "${XCMAX_DR_GIT_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' "$XCMAX_DR_GIT_SHA" >/var/lib/xcmax-dr/DEPLOYED_GIT_SHA
  chmod 0644 /var/lib/xcmax-dr/DEPLOYED_GIT_SHA
fi
echo "DR 脚本与 cron 已安装"
