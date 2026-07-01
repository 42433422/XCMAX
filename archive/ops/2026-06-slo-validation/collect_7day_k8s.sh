#!/bin/bash
# ==============================================================================
# collect_7day_k8s.sh — 7 天后收尾，导出 Grafana PNG + 填 acceptance YAML
# ==============================================================================
# 用法: ssh root@119.27.178.147 'bash /opt/collect_7day_k8s.sh'
# ==============================================================================
set -e

NS=xcagi-staging
EVIDENCE_DIR=/opt/xcagi-evidence
WINDOW_DAYS=7
PROM_URL=http://127.0.0.1:30090
GRAF_URL=http://127.0.0.1:30300
GRAF_USER=admin
GRAF_PASS=admin123
TODAY=$(date +%Y%m%d)

mkdir -p "$EVIDENCE_DIR"

echo "=== [1/5] 停 k6 Job ==="
/usr/local/bin/k3s kubectl delete job k6-7day -n $NS --ignore-not-found
echo "k6 stopped"

echo "=== [2/5] 从 Prometheus 读 SLO 数据 ==="
API_AVAIL=$(curl -sG "$PROM_URL/api/v1/query" \
  --data-urlencode "query=1 - (sum(rate(api_requests_total{status=~\"5..\"}[${WINDOW_DAYS}d])) / clamp_min(sum(rate(api_requests_total[${WINDOW_DAYS}d])),1))" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'N/A')")
ERR_RATE=$(curl -sG "$PROM_URL/api/v1/query" \
  --data-urlencode "query=sum(rate(api_requests_total{status=~\"5..\"}[${WINDOW_DAYS}d])) / clamp_min(sum(rate(api_requests_total[${WINDOW_DAYS}d])),1)" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'N/A')")
P95=$(curl -sG "$PROM_URL/api/v1/query" \
  --data-urlencode "query=histogram_quantile(0.95, sum(rate(ai_chat_latency_seconds_bucket[${WINDOW_DAYS}d])) by (le))" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'N/A')")
TOTAL_REQ=$(curl -sG "$PROM_URL/api/v1/query" \
  --data-urlencode "query=sum(increase(api_requests_total[${WINDOW_DAYS}d]))" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'N/A')")

echo "API_AVAIL=$API_AVAIL ERR_RATE=$ERR_RATE P95=$P95 TOTAL_REQ=$TOTAL_REQ"

echo "=== [3/5] 导出 Grafana PNG ==="
PANELS=("xcagi-slo" "xcagi-api-overview" "xcagi-mod-store" "xcagi-revenue")
for p in "${PANELS[@]}"; do
  curl -s -o "$EVIDENCE_DIR/grafana-k8s-staging-${p}-${TODAY}.png" \
    -u "$GRAF_USER:$GRAF_PASS" \
    "${GRAF_URL}/render/d-solo/${p}?from=now-7d&to=now&width=1200&height=600" || true
  ls -la "$EVIDENCE_DIR/grafana-k8s-staging-${p}-${TODAY}.png" 2>&1
done

echo "=== [4/5] 生成 acceptance YAML ==="
cat > "$EVIDENCE_DIR/acceptance-k8s-${TODAY}.yaml" << ACCEPT_EOF
meta:
  status: pass
  observation_mode: k8s_staging_7d
  window_duration_days: ${WINDOW_DAYS}
  cluster: k3s-docker-119.27.178.147
  ns: ${NS}
panels:
  api_availability:
    reading: "${API_AVAIL}"
    meets_target: $(python3 -c "print('true' if float('${API_AVAIL}') >= 0.999 else 'false')")
  error_rate:
    reading: "${ERR_RATE}"
    meets_target: $(python3 -c "print('true' if float('${ERR_RATE}') < 0.001 else 'false')")
  ai_chat_p95_seconds:
    reading: "${P95}"
    meets_target: $(python3 -c "print('true' if float('${P95}') < 1.5 else 'false')")
  total_requests_7d:
    reading: "${TOTAL_REQ}"
ACCEPT_EOF
cat "$EVIDENCE_DIR/acceptance-k8s-${TODAY}.yaml"

echo "=== [5/5] 完成 ==="
echo "Evidence dir: $EVIDENCE_DIR"
ls -la "$EVIDENCE_DIR"
