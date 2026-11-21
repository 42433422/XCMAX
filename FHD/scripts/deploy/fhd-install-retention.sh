#!/usr/bin/env bash
# 安装服务器文件保留策略：logrotate + systemd-tmpfiles。
#
# 用法（CVM 上执行）:
#   sudo bash fhd-install-retention.sh
#
# 安装后日志按 14 份/30 天轮转压缩，临时目录内容保留 7 天。
# 应用内置的 file_retention_janitor 可随后用
# MODSTORE_RETENTION_JANITOR_ENABLED=0 关闭，避免重复清理。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

install -D -m 0644 "$SCRIPT_DIR/logrotate-xcmax.conf" /etc/logrotate.d/xcmax
install -D -m 0644 "$SCRIPT_DIR/systemd-tmpfiles-xcmax.conf" /etc/tmpfiles.d/xcmax.conf

mkdir -p /opt/xcmax/tmp /var/tmp/xcmax /var/log/xcmax

logrotate -d /etc/logrotate.d/xcmax >/dev/null
systemd-tmpfiles --create /etc/tmpfiles.d/xcmax.conf

echo "[install] logrotate: /etc/logrotate.d/xcmax"
echo "[install] tmpfiles:  /etc/tmpfiles.d/xcmax.conf"
echo "[install] 完成"
