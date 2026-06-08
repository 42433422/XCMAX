#!/bin/bash
# recover_staging_console.sh — SSH 不可用时，在腾讯云 VNC/控制台粘贴执行
# 目标：恢复 sshd → 看完 fix 日志 → 补拉镜像 → 确认 API/k6
set -euo pipefail

echo "=== [1] 恢复 sshd ==="
systemctl start sshd 2>/dev/null || service sshd start 2>/dev/null || true
systemctl enable sshd 2>/dev/null || true
ss -tlnp | grep ':22 ' || echo "WARN: 22 仍未监听，查 journalctl -u sshd"

echo "=== [2] fix 日志末尾 ==="
tail -80 /opt/fix.log 2>/dev/null || echo "无 /opt/fix.log"

echo "=== [3] 补拉 Grafana/k6（若仍 ImagePullBackOff） ==="
pull_tag() {
  local name=$1 alt=$2
  docker pull "$alt" && docker tag "$alt" "$name" || docker pull "$name" || true
}
pull_tag grafana/grafana:10.2.0 docker.m.daocloud.io/grafana/grafana:10.2.0
pull_tag grafana/k6:0.50.0 docker.m.daocloud.io/grafana/k6:0.50.0
pull_tag prom/prometheus:v2.45.0 docker.m.daocloud.io/prom/prometheus:v2.45.0

KUB=/usr/local/bin/k3s
NS=xcagi-staging
$KUB kubectl delete pod -n $NS -l 'app in (grafana,prometheus,k6)' --force --grace-period=0 2>/dev/null || true

echo "=== [4] 若 fix 未跑完，重跑 ==="
if ! grep -q 'fix 完成' /opt/fix.log 2>/dev/null; then
  nohup bash /opt/fix_k8s_staging_live.sh >> /opt/fix.log 2>&1 &
  echo "fix 已重跑 pid=$!"
fi

echo "=== [5] 状态 ==="
sleep 15
$KUB kubectl get pods -n $NS
$KUB kubectl get job k6-7day -n $NS 2>/dev/null || true
curl -sf http://127.0.0.1:30080/health/liveness && echo " API OK" || echo " API not ready"
curl -sf http://127.0.0.1:30090/-/healthy && echo " Prom OK" || true
curl -sf http://127.0.0.1:30300/login -o /dev/null && echo " Grafana OK" || true
echo "=== 完成：请本机再试 ssh root@119.27.178.147 ==="
