#!/bin/bash
# ==============================================================================
# deploy_k8s_staging.sh — 在 119.27.178.147 上 K8s 集群跑 FHD 7 天 SLO
# ==============================================================================
# 时间: 2026-06-05
# 策略: K3s (--docker) + 预构建 FHD API 镜像 + apply FHD/k8s 清单 + 监控栈 + k6
#       7 天后跑 collect_7day_k8s.sh 一键收尾
# 用法: scp + ssh 执行
#   scp deploy_k8s_staging.sh root@119.27.178.147:/opt/
#   ssh root@119.27.178.147 'bash /opt/deploy_k8s_staging.sh 2>&1 | tee /opt/deploy.log'
# ==============================================================================
set -e

DEPLOY_DIR=/opt/xcagi-k8s-staging
K3S_DIR=/etc/rancher/k3s
FHD_SRC=/opt/fhd-full
NS=xcagi-staging

mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

echo "=== [1/9] 收尾：停 docker compose 残留 + 旧 k3s ==="
cd /opt/xcagi-staging 2>/dev/null && docker compose down -v 2>&1 | tail -5 || true
systemctl stop k3s 2>/dev/null || true
/usr/local/bin/k3s-killall.sh 2>/dev/null || true
pkill -9 -f k3s 2>/dev/null || true
pkill -9 -f containerd-shim 2>/dev/null || true
pkill -9 -f kubelet 2>/dev/null || true
sleep 5
rm -rf /var/lib/rancher /etc/rancher/k3s /run/k3s 2>/dev/null || true
echo "cleanup done"

echo "=== [2/9] 安装 Docker（Aliyun mirror） ==="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh --mirror Aliyun
  systemctl enable docker
  systemctl start docker
fi
docker version | head -3
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://registry.cn-hangzhou.aliyuncs.com",
    "https://docker.mirrors.ustc.edu.cn"
  ],
  "log-driver": "json-file",
  "log-opts": {"max-size": "100m", "max-file": "3"}
}
EOF
systemctl restart docker
docker info 2>&1 | grep -i "registry mirror" -A 3

echo "=== [3/9] 装 K3s（--docker runtime + 国内源，cgroup v1 兼容版） ==="
export INSTALL_K3S_MIRROR=cn
export INSTALL_K3S_SKIP_SELINUX_RPM=true
export INSTALL_K3S_VERSION="v1.31.11+k3s1"
export INSTALL_K3S_EXEC="--docker --disable traefik --disable metrics-server --write-kubeconfig-mode 644 --kubelet-arg=image-gc-high-threshold=80 --kubelet-arg=image-gc-low-threshold=70"
curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn INSTALL_K3S_SKIP_SELINUX_RPM=true INSTALL_K3S_VERSION="v1.31.11+k3s1" sh -
systemctl enable k3s 2>/dev/null || true
systemctl restart k3s
echo "K3s install done"

echo "=== [4/9] 等待 K3s ready ==="
for i in {1..60}; do
  if /usr/local/bin/k3s kubectl get nodes 2>/dev/null | grep -q " Ready"; then
    echo "K3s ready after ${i}*5s"
    break
  fi
  sleep 5
done
/usr/local/bin/k3s kubectl get nodes -o wide || true
/usr/local/bin/k3s kubectl get pods -A || true

echo "=== [5/9] 准备 FHD API 镜像（本地 build，Aliyun pip） ==="
ls -la "$FHD_SRC" | head -10
cd "$FHD_SRC"
# Stage 共享小包 xcagi_common 进 FHD 构建上下文（Dockerfile 会 COPY xcagi_common /app/xcagi_common）。
# 位于仓库根 packages/xcagi_common；构建上下文是 FHD，需先拷进来，否则新代码 app.middleware.csrf 启动即崩。
if [ ! -d "$FHD_SRC/xcagi_common" ]; then
  for CAND in "$FHD_SRC/../packages/xcagi_common/xcagi_common" /root/XCMAX/packages/xcagi_common/xcagi_common /opt/XCMAX/packages/xcagi_common/xcagi_common; do
    if [ -d "$CAND" ]; then cp -r "$CAND" "$FHD_SRC/xcagi_common"; echo "staged xcagi_common from $CAND"; break; fi
  done
fi
docker pull docker.m.daocloud.io/library/python:3.11-slim || docker pull python:3.11-slim
docker tag docker.m.daocloud.io/library/python:3.11-slim python:3.11-slim 2>/dev/null || true
docker build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  --build-arg PIP_TRUSTED_HOST=mirrors.aliyun.com \
  -f docker/Dockerfile.fhd-api \
  -t xcagi-fhd-api:staging .
echo "image built:"
docker images xcagi-fhd-api:staging

echo "=== [6/9] apply 命名空间 + Redis + ConfigMap ==="
cat > "$DEPLOY_DIR/00-namespace.yaml" << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: xcagi-staging
EOF
cat > "$DEPLOY_DIR/01-redis.yaml" << 'EOF'
apiVersion: v1
kind: Service
metadata:
  name: redis-service
  namespace: xcagi-staging
spec:
  ports:
  - port: 6379
    targetPort: 6379
  selector:
    app: redis
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: xcagi-staging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
EOF
cat > "$DEPLOY_DIR/02-configmap.yaml" << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: xcagi-config
  namespace: xcagi-staging
data:
  redis_url: "redis://redis-service:6379"
  # 健康检查 _check_redis 读大写 REDIS_URL（默认 localhost:6379），必须显式给出，否则 readiness 永远 503。
  REDIS_URL: "redis://redis-service:6379/0"
  # 本部署未挂载 RASA 模型；嵌入式无模型会被 readiness 判为 degraded（非 healthy/disabled）。
  # 显式禁用，使 _check_rasa_nlu 返回 disabled（可接受），不阻塞就绪。其余意图引擎(rule/distilled/bert/deepseek)不受影响。
  ENABLE_RASA: "0"
  DATABASE_URL: "sqlite:////app/data/staging.db"
  FHD_SKIP_ALEMBIC: "1"
  ADMIN_USERNAME: "admin"
  ADMIN_PASSWORD: "staging-admin"
  flask_env: "production"
  log_level: "INFO"
  FHD_ENV: "production"
  CACHE_REDIS_URL: "redis://redis-service:6379"
  XCAGI_NEURO_BUS_DEDUP: "1"
  XCAGI_NEURO_BUS_CIRCUIT: "1"
  XCAGI_NEURO_BUS_RATE_LIMIT: "1"
  XCAGI_NEURO_BUS_TRACE: "1"
  XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE: "0.1"
  XCAGI_NEURO_BUS_LIFELINE: "1"
  XCAGI_NEURO_BUS_DLQ_AUTO: "1"
  XCAGI_NEURO_BUS_SLA_LOG: "1"
  # Shipment write path goes event-primary on staging (canary before flipping the
  # global XCAGI_EVENT_PRIMARY default). Fail-safe: degrades to direct writes if the
  # bus is down. Mirror this in helm/xcagi/values.yaml.
  XCAGI_EVENT_PRIMARY_SHIPMENT: "1"
  XCAGI_GLOBAL_RATE_LIMIT: "1"
  XCAGI_GLOBAL_RATE_LIMIT_MAX: "300"
  XCAGI_GLOBAL_RATE_LIMIT_WINDOW: "60"
  XCAGI_GUNICORN_WORKERS: "2"
EOF
/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/00-namespace.yaml"
/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/01-redis.yaml"
/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/02-configmap.yaml"

echo "=== [7/9] apply FHD API Deployment + Service ==="
cat > "$DEPLOY_DIR/03-fhd-api.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: xcagi
  namespace: xcagi-staging
  labels:
    app: xcagi
    version: v10.0.0
spec:
  replicas: 2
  selector:
    matchLabels:
      app: xcagi
  template:
    metadata:
      labels:
        app: xcagi
        version: v10.0.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: xcagi
        image: xcagi-fhd-api:staging
        imagePullPolicy: Never
        ports:
        - containerPort: 5000
          name: http
        envFrom:
        - configMapRef:
            name: xcagi-config
        # 探针修正：liveness 打轻量 /health/liveness，readiness 打深度 /health/readiness；
        # 加 startupProbe 兜住慢启动（BERT/意图引擎初始化），避免 liveness 在初始化期误杀 → CrashLoopBackOff。
        startupProbe:
          httpGet:
            path: /health/liveness
            port: 5000
          periodSeconds: 10
          failureThreshold: 36
          timeoutSeconds: 5
        livenessProbe:
          httpGet:
            path: /health/liveness
            port: 5000
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 6
        readinessProbe:
          httpGet:
            path: /health/readiness
            port: 5000
          periodSeconds: 15
          timeoutSeconds: 10
          failureThreshold: 8
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: xcagi-service
  namespace: xcagi-staging
spec:
  type: NodePort
  ports:
  - port: 80
    targetPort: 5000
    nodePort: 30080
    protocol: TCP
    name: http
  selector:
    app: xcagi
EOF
/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/03-fhd-api.yaml"

echo "=== [8/9] apply 监控栈（Prometheus PVC + Loki + Grafana） ==="
cat > "$DEPLOY_DIR/04-prometheus.yaml" << 'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: xcagi-staging
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prometheus-data
  namespace: xcagi-staging
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 15Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: xcagi-staging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      serviceAccountName: prometheus
      containers:
      - name: prometheus
        image: prom/prometheus:v2.53.0
        args:
        - "--config.file=/etc/prometheus/prometheus.yml"
        - "--storage.tsdb.path=/prometheus"
        - "--storage.tsdb.retention.time=8d"
        - "--web.enable-lifecycle"
        ports:
        - containerPort: 9090
        volumeMounts:
        - name: config
          mountPath: /etc/prometheus
        - name: data
          mountPath: /prometheus
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 2Gi
      volumes:
      - name: config
        configMap:
          name: prometheus-config
      - name: data
        persistentVolumeClaim:
          claimName: prometheus-data
---
apiVersion: v1
kind: Service
metadata:
  name: prometheus
  namespace: xcagi-staging
spec:
  type: NodePort
  ports:
  - port: 9090
    targetPort: 9090
    nodePort: 30090
  selector:
    app: prometheus
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: xcagi-staging
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
    scrape_configs:
      - job_name: 'xcagi-backend'
        metrics_path: /metrics
        static_configs:
          - targets: ['xcagi-service:80']
            labels:
              env: staging
              service: fhd
      - job_name: 'k6'
        static_configs:
          - targets: ['k6-service:6565']
            labels:
              env: staging
              service: k6
EOF
/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/04-prometheus.yaml"

LOKI_MANIFEST="$FHD_SRC/k8s/monitoring/loki/loki-deployment.yml"
LOKI_PVC="$FHD_SRC/k8s/monitoring/loki/loki-pvc.yml"
PROMTAIL_DS="$FHD_SRC/k8s/monitoring/loki/promtail-daemonset.yml"
if [[ -f "$LOKI_PVC" && -f "$LOKI_MANIFEST" ]]; then
  sed 's/namespace: monitoring/namespace: xcagi-staging/g' "$LOKI_PVC" > "$DEPLOY_DIR/04b-loki-pvc.yaml"
  sed 's/namespace: monitoring/namespace: xcagi-staging/g' "$LOKI_MANIFEST" > "$DEPLOY_DIR/04b-loki.yaml"
  /usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/04b-loki-pvc.yaml"
  /usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/04b-loki.yaml"
  if [[ -f "$PROMTAIL_DS" ]]; then
    sed 's/namespace: monitoring/namespace: xcagi-staging/g' "$PROMTAIL_DS" > "$DEPLOY_DIR/04c-promtail.yaml"
    /usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/04c-promtail.yaml"
  fi
else
  echo "WARN: Loki manifests missing under $FHD_SRC/k8s/monitoring/loki" >&2
fi

# grafana-dashboards ConfigMap 由 4 份仓库仪表盘（+ 兼容 slo）构建，见下方 kubectl create 步骤。
cat > "$DEPLOY_DIR/05-grafana.yaml" << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-provisioning
  namespace: xcagi-staging
data:
  datasources.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        uid: prometheus
        access: proxy
        url: http://prometheus:9090
        isDefault: true
  dashboards.yaml: |
    apiVersion: 1
    providers:
      - name: 'xcagi'
        folder: 'xcagi'
        type: file
        options:
          path: /var/lib/grafana/dashboards
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: xcagi-staging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - name: grafana
        image: grafana/grafana:10.2.0
        env:
        - name: GF_SECURITY_ADMIN_PASSWORD
          value: admin123
        - name: GF_USERS_ALLOW_SIGN_UP
          value: "false"
        # 仪表盘 /render PNG 渲染需外置 image-renderer 服务（见下方 Deployment）。
        - name: GF_RENDERING_SERVER_URL
          value: http://grafana-image-renderer:8081/render
        - name: GF_RENDERING_CALLBACK_URL
          value: http://grafana:3000/
        - name: GF_LOG_FILTERS
          value: rendering:info
        ports:
        - containerPort: 3000
        volumeMounts:
        - name: datasources
          mountPath: /etc/grafana/provisioning/datasources
        - name: dashboards-prov
          mountPath: /etc/grafana/provisioning/dashboards
        - name: dashboards
          mountPath: /var/lib/grafana/dashboards
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 1Gi
      volumes:
      - name: datasources
        configMap:
          name: grafana-provisioning
          items:
          - key: datasources.yaml
            path: datasources.yaml
      - name: dashboards-prov
        configMap:
          name: grafana-provisioning
          items:
          - key: dashboards.yaml
            path: dashboards.yaml
      - name: dashboards
        configMap:
          name: grafana-dashboards
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: xcagi-staging
spec:
  type: NodePort
  ports:
  - port: 3000
    targetPort: 3000
    nodePort: 30300
  selector:
    app: grafana
---
# Grafana 图像渲染器（/render PNG 依赖；用 Aliyun 镜像，国内可拉取）。
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana-image-renderer
  namespace: xcagi-staging
  labels:
    app: grafana-image-renderer
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana-image-renderer
  template:
    metadata:
      labels:
        app: grafana-image-renderer
    spec:
      containers:
      - name: renderer
        image: registry.cn-hangzhou.aliyuncs.com/acs/grafana-image-renderer:latest
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8081
        env:
        - name: ENABLE_METRICS
          value: "false"
        - name: RENDERING_MODE
          value: "default"
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: grafana-image-renderer
  namespace: xcagi-staging
spec:
  selector:
    app: grafana-image-renderer
  ports:
  - port: 8081
    targetPort: 8081
EOF

# 构建 grafana-dashboards ConfigMap：用仓库 4 份仪表盘，${DS_PROMETHEUS} → 线上 Prometheus 数据源 uid。
GDASH_SRC="$FHD_SRC/k8s/monitoring/grafana/dashboards"
GDASH_TMP=/tmp/xcagi-gdash-deploy
rm -rf "$GDASH_TMP" && mkdir -p "$GDASH_TMP"
DS_UID=$(/usr/local/bin/k3s kubectl exec -n "$NS" deploy/grafana -c grafana -- sh -c \
  'wget -qO- --header="Authorization: Basic $(printf admin:admin123 | base64)" http://127.0.0.1:3000/api/datasources/name/Prometheus 2>/dev/null' \
  | grep -o '"uid":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
if [ -z "${DS_UID:-}" ] || [ "$DS_UID" = "null" ]; then DS_UID=prometheus; fi
echo "Grafana Prometheus datasource uid=$DS_UID"
for f in xcagi-api-overview xcagi-infrastructure xcagi-mod-store xcagi-neurobus xcagi-slo; do
  if [ -f "$GDASH_SRC/$f.json" ]; then
    sed "s/\${DS_PROMETHEUS}/$DS_UID/g" "$GDASH_SRC/$f.json" > "$GDASH_TMP/$f.json"
  fi
done
/usr/local/bin/k3s kubectl -n "$NS" create configmap grafana-dashboards \
  --from-file="$GDASH_TMP" \
  --dry-run=client -o yaml | /usr/local/bin/k3s kubectl apply -f -

/usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/05-grafana.yaml"

echo "=== [9/9] k6 压测 168h（SSOT ConfigMap + Job，窗口进行中勿重建 Job） ==="
K6_SYNC="$FHD_SRC/scripts/observability/sync_k6_configmap.sh"
K6_CM="$FHD_SRC/k8s/monitoring/k6-configmap.yaml"
K6_JOB="$FHD_SRC/k8s/monitoring/k6-7day-job.yaml"
if [[ -x "$K6_SYNC" ]]; then
  KUBECTL="/usr/local/bin/k3s kubectl" bash "$K6_SYNC" --namespace "$NS" --output "$DEPLOY_DIR/k6-configmap.yaml"
  /usr/local/bin/k3s kubectl apply -f "$DEPLOY_DIR/k6-configmap.yaml"
elif [[ -f "$K6_CM" ]]; then
  /usr/local/bin/k3s kubectl apply -f "$K6_CM"
else
  echo "WARN: k6 SSOT sync script missing; skip ConfigMap apply" >&2
fi
if [[ -f "$K6_JOB" ]]; then
  /usr/local/bin/k3s kubectl apply -f "$K6_JOB"
else
  echo "WARN: k6-7day-job.yaml missing at $K6_JOB" >&2
fi

echo ""
echo "=== 等待 Pod ready ==="
sleep 30
/usr/local/bin/k3s kubectl get pods -n $NS
echo ""
echo "=== NodePort 映射 ==="
echo "  - FHD API:     http://127.0.0.1:30080"
echo "  - Prometheus:  http://127.0.0.1:30090"
echo "  - Grafana:     http://127.0.0.1:30300 (admin/admin123)"
echo "  - k6:          Job k6-7day, 168h"
echo ""
echo "=== 验证 ==="
curl -s http://127.0.0.1:30080/health/liveness | head -3
echo ""
curl -s http://127.0.0.1:30090/api/v1/targets 2>&1 | head -100
echo ""
echo "=== 部署完成！跑 7 天后执行 collect_7day_k8s.sh ==="
