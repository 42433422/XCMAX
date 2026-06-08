#!/bin/bash
# fix_k8s_staging_live.sh — 修复 ImagePullBackOff + API 缺依赖（快速 patch + 可选全量 build）
set -euo pipefail

NS=xcagi-staging
KUB=/usr/local/bin/k3s
FHD_SRC=/opt/fhd-full
DEPLOY_DIR=/opt/xcagi-k8s-staging
PIP_IDX=https://mirrors.aliyun.com/pypi/simple/
PIP_HOST=mirrors.aliyun.com

pull_img() {
  local name=$1
  shift
  local candidates=("$name" "$@")
  for c in "${candidates[@]}"; do
    echo "  try pull $c"
    if docker pull "$c"; then
      if [ "$c" != "$name" ]; then docker tag "$c" "$name"; fi
      echo "  ok: $name"
      return 0
    fi
  done
  echo "  FAIL: $name"
  return 1
}

echo "=== [1/5] 预拉镜像（DaoCloud 备用） ==="
pull_img redis:7-alpine \
  docker.m.daocloud.io/library/redis:7-alpine || true
pull_img prom/prometheus:v2.45.0 \
  docker.m.daocloud.io/prom/prometheus:v2.45.0 || true
pull_img grafana/grafana:10.2.0 \
  docker.m.daocloud.io/grafana/grafana:10.2.0 || true
pull_img grafana/k6:0.50.0 \
  docker.m.daocloud.io/grafana/k6:0.50.0 || true

echo "=== [2/5] 更新 Deployment + 缩容去重 ==="
$KUB kubectl scale deployment/redis deployment/prometheus deployment/grafana deployment/xcagi -n "$NS" --replicas=1 2>/dev/null || true
$KUB kubectl set image deployment/redis redis=redis:7-alpine -n "$NS"
$KUB kubectl set image deployment/prometheus prometheus=prom/prometheus:v2.45.0 -n "$NS"
$KUB kubectl set image deployment/grafana grafana=grafana/grafana:10.2.0 -n "$NS"
$KUB kubectl delete pod -n "$NS" -l 'app in (redis,prometheus,grafana)' --force --grace-period=0 2>/dev/null || true

echo "=== [3/5] 快速 patch API 镜像（pip install requests，免全量 rebuild） ==="
if docker image inspect xcagi-fhd-api:staging >/dev/null 2>&1; then
  docker rm -f xcagi-patch 2>/dev/null || true
  docker run -d --name xcagi-patch --user root --entrypoint sleep xcagi-fhd-api:staging infinity
  docker exec xcagi-patch pip install --default-timeout=120 \
    -i "$PIP_IDX" --trusted-host "$PIP_HOST" \
    'requests>=2.31.0' 'httpx[socks]==0.26.0' 'prometheus_client>=0.19.0' || true
  docker commit \
    --change='ENTRYPOINT ["/entrypoint.sh"]' \
    --change='CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "--graceful-timeout", "30", "-k", "uvicorn.workers.UvicornWorker", "XCAGI.run_fastapi:app"]' \
    xcagi-patch xcagi-fhd-api:staging
  docker rm -f xcagi-patch
  echo "API image patched"
else
  echo "WARN: xcagi-fhd-api:staging not found, skip patch"
fi
$KUB kubectl set image deployment/xcagi xcagi=xcagi-fhd-api:staging -n "$NS"
$KUB kubectl rollout restart deployment/xcagi -n "$NS"

echo "=== [4/5] 重建 k6 Job ==="
$KUB kubectl delete job k6-7day -n "$NS" --ignore-not-found
if [ -f "$DEPLOY_DIR/06-k6.yaml" ]; then
  sed -i 's|registry.cn-hangzhou.aliyuncs.com/acs/grafana-k6:0.50.0|grafana/k6:0.50.0|g' "$DEPLOY_DIR/06-k6.yaml"
  $KUB kubectl apply -f "$DEPLOY_DIR/06-k6.yaml"
fi

echo "=== [5/5] 等待 Pod（最多 5 分钟） ==="
for i in {1..30}; do
  sleep 10
  $KUB kubectl get pods -n "$NS" --no-headers
  running=$($KUB kubectl get pods -n "$NS" --no-headers 2>/dev/null | awk '$3=="Running" && $2 ~ /^1\/1/' | wc -l)
  echo "running_ready=$running"
  if [ "$running" -ge 4 ]; then break; fi
done

echo "=== 健康检查 ==="
curl -sf http://127.0.0.1:30080/health/liveness && echo " API OK" || echo " API not ready"
$KUB kubectl get pods -n "$NS"
$KUB kubectl get job k6-7day -n "$NS" 2>/dev/null || true
echo "=== fix 完成 ==="
