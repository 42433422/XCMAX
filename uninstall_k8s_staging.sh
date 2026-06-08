#!/bin/bash
# ==============================================================================
# uninstall_k8s_staging.sh — 卸载 K3s + 清理
# ==============================================================================
set -e

echo "=== [1/3] 停所有 k8s 资源 ==="
/usr/local/bin/k3s kubectl delete namespace xcagi-staging --ignore-not-found 2>&1 | tail -5
sleep 5

echo "=== [2/3] 卸 K3s ==="
if [ -x /usr/local/bin/k3s-uninstall.sh ]; then
  /usr/local/bin/k3s-uninstall.sh 2>&1 | tail -10
fi
rm -rf /var/lib/rancher /etc/rancher /run/k3s /var/log/k3s*

echo "=== [3/3] 清 Docker 镜像 ==="
docker rmi xcagi-fhd-api:staging 2>/dev/null || true
echo "uninstall done"
