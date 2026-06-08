#!/bin/bash
# ==============================================================================
# deploy_staging.sh — 在 119.27.178.147 上部署 FHD staging 7 天 SLO 栈
# ==============================================================================
# 时间: 2026-06-05
# 作用: docker compose 跑 FHD + Prometheus + Grafana + k6
#       7 天后跑 collect_7day.sh 一键收尾
# 用法: ssh root@119.27.178.147 'bash /root/deploy_staging.sh'
# ==============================================================================
set -e

DEPLOY_DIR=/opt/xcagi-staging
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

echo "=== [1/6] 停 k3s（不卸） ==="
pkill -f "/usr/local/bin/k3s" 2>/dev/null || true
pkill -f "containerd-shim" 2>/dev/null || true
sleep 3
echo "k3s stopped (binary保留在 /usr/local/bin/k3s，重启用 k3s server &)"

echo "=== [2/6] 准备 FHD 目录 ==="
ls -la /opt/fhd-full/ 2>&1 | head -5
echo "(使用 /opt/fhd-full 现有代码，不动)"

echo "=== [3/6] 写 docker-compose.yml ==="
cat > "$DEPLOY_DIR/docker-compose.yml" << 'COMPOSE_EOF'
services:
  fhd-redis:
    image: registry.cn-hangzhou.aliyuncs.com/library/redis:7-alpine
    container_name: xcagi-staging-redis
    restart: unless-stopped
    ports:
      - "127.0.0.1:16380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

  fhd-api:
    image: registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim
    container_name: xcagi-staging-api
    restart: unless-stopped
    working_dir: /app
    command: >
      bash -c "
        apt-get update -qq &&
        apt-get install -y -qq --no-install-recommends curl gcc libpq-dev &&
        pip install --no-cache-dir -r requirements.txt &&
        pip install --no-cache-dir gunicorn fastapi uvicorn[standard] prometheus-client &&
        gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 60 wsgi:app
      "
    ports:
      - "127.0.0.1:5500:5000"
    environment:
      CACHE_REDIS_URL: redis://fhd-redis:6379/0
      PYTHONUNBUFFERED: "1"
      PYTHONPATH: /app
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - /opt/fhd-full:/app:ro
    depends_on:
      fhd-redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  prometheus:
    image: registry.cn-hangzhou.aliyuncs.com/acs/prometheus:v2.45.0
    container_name: xcagi-staging-prometheus
    restart: unless-stopped
    ports:
      - "127.0.0.1:5901:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=8d"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus

  grafana:
    image: registry.cn-hangzhou.aliyuncs.com/acs/grafana:10.2.0
    container_name: xcagi-staging-grafana
    restart: unless-stopped
    ports:
      - "127.0.0.1:5902:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin123
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana

  k6:
    image: registry.cn-hangzhou.aliyuncs.com/acs/grafana-k6:0.50.0
    container_name: xcagi-staging-k6
    restart: "no"
    command: >
      run
      --vus 5
      --duration 168h
      --out json=/tmp/k6-results.json
      -e BASE_URL=http://fhd-api:5000
      - <(echo 'import http from "k6/http"; export default function() { http.get(__ENV.BASE_URL + "/api/health"); };')
    depends_on:
      fhd-api:
        condition: service_healthy
    volumes:
      - k6-data:/tmp

volumes:
  prometheus-data:
  grafana-data:
  k6-data:
COMPOSE_EOF

echo "=== [4/6] 写 prometheus.yml ==="
cat > "$DEPLOY_DIR/prometheus.yml" << 'PROM_EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'xcagi-staging-api'
    metrics_path: /metrics
    static_configs:
      - targets: ['fhd-api:5000']
        labels:
          env: staging
          service: fhd
PROM_EOF

echo "=== [5/6] Grafana provisioning (待人工用 /Users/a4243342/Desktop/XCMAX/FHD/observability/grafana/ 里的 dashboards 复制) ==="
mkdir -p "$DEPLOY_DIR/grafana/provisioning/datasources"
mkdir -p "$DEPLOY_DIR/grafana/provisioning/dashboards"
mkdir -p "$DEPLOY_DIR/grafana/dashboards"
cat > "$DEPLOY_DIR/grafana/provisioning/datasources/prometheus.yml" << 'GRAF_EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
GRAF_EOF
cat > "$DEPLOY_DIR/grafana/provisioning/dashboards/xcagi.yml" << 'GRAF_EOF'
apiVersion: 1
providers:
  - name: 'xcagi'
    folder: 'xcagi'
    type: file
    disableDeletion: false
    options:
      path: /var/lib/grafana/dashboards
GRAF_EOF
echo "(复制 4 个 dashboard JSON 到 $DEPLOY_DIR/grafana/dashboards/ - 见下)"

# Copy dashboards from FHD
cp /Users/a4243342/Desktop/XCMAX/FHD/observability/grafana/dashboards/*.json "$DEPLOY_DIR/grafana/dashboards/" 2>/dev/null || \
  cp /opt/fhd-full/observability/grafana/dashboards/*.json "$DEPLOY_DIR/grafana/dashboards/" 2>/dev/null || \
  echo "WARNING: no dashboards copied. Run: scp -r /Users/a4243342/Desktop/XCMAX/FHD/observability/grafana/dashboards/* $DEPLOY_DIR/grafana/dashboards/"
ls -la "$DEPLOY_DIR/grafana/dashboards/" 2>&1

echo "=== [6/6] docker compose up ==="
cd "$DEPLOY_DIR"
docker compose up -d 2>&1 | tail -20

echo ""
echo "=== 验证 ==="
sleep 30
docker compose ps
echo "---"
curl -s http://127.0.0.1:5500/api/health 2>&1 | head -3
echo "---"
curl -s http://127.0.0.1:5901/api/v1/targets 2>&1 | head -50
echo "---"
curl -s -u admin:admin123 http://127.0.0.1:5902/api/search?type=dash-db 2>&1 | head -20

echo ""
echo "=== 部署完成！ ==="
echo "  - FHD API:    http://127.0.0.1:5500"
echo "  - Prometheus: http://127.0.0.1:5901"
echo "  - Grafana:    http://127.0.0.1:5902 (admin/admin123)"
echo "  - k6:         在容器内跑 168h（7 天）"
echo "  - 7 天后跑 collect_7day.sh 一键收尾"
