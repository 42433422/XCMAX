#!/bin/bash
# ==============================================================================
# uninstall_staging.sh — 一键卸 K3s + FHD staging 全栈
# ==============================================================================
# 作用: 卸 K3s（保留二进制）+ 卸 FHD/Prometheus/Grafana/k6 容器
#       不动现有 5 个 modstore_deploy 容器
# 用法: ssh root@119.27.178.147 'bash /root/uninstall_staging.sh'
# ==============================================================================
set -e

DEPLOY_DIR=/opt/xcagi-staging

echo "=== [1/4] 卸 FHD staging docker compose 栈 ==="
if [ -d "$DEPLOY_DIR" ]; then
  cd "$DEPLOY_DIR"
  docker compose down -v 2>&1 | tail -10
  echo "FHD staging 栈已卸"
else
  echo "$DEPLOY_DIR 不存在，跳过"
fi

echo "=== [2/4] 卸 K3s（保留二进制 /usr/local/bin/k3s）==="
if [ -x /usr/local/bin/k3s-uninstall.sh ]; then
  /usr/local/bin/k3s-uninstall.sh 2>&1 | tail -10
elif [ -x /usr/local/bin/k3s ]; then
  pkill -9 -f "/usr/local/bin/k3s" 2>&1 || true
  pkill -9 -f "containerd-shim" 2>&1 || true
  sleep 3
  echo "K3s 进程已停（未走官方 uninstall.sh，目录残留）"
fi

echo "=== [3/4] 清理 K3s 数据 ==="
rm -rf /var/lib/rancher
rm -rf /run/k3s
rm -rf /var/log/k3s-server*.log
echo "K3s 数据已清"

echo "=== [4/4] 恢复备份（如有） ==="
if [ -d /root/pre-k3s-backup-20260605 ]; then
  echo "发现 2026-06-05 K3s 安装前备份: /root/pre-k3s-backup-20260605/"
  echo "  (内容: /etc-pre-k3s.tgz)"
  echo "  如需还原: cd / && tar xzf /root/pre-k3s-backup-20260605/etc-pre-k3s.tgz"
fi

echo ""
echo "=== 验证 ==="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 | head -10
echo "(应只剩原 5 个 modstore_deploy 容器)"

ss -tln 2>&1 | grep -E "6443|5500|5901|5902" || echo "✓ K3s/FHD staging 端口已空"

echo ""
echo "=== 卸载完成 ==="
echo "  - K3s 进程停 + 数据清 + 二进制保留（如要彻底卸：rm /usr/local/bin/k3s /usr/local/bin/k3s-uninstall.sh）"
echo "  - FHD staging 栈卸（容器、卷、网络）"
echo "  - 5 个 modstore_deploy 容器未动"
