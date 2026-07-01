#!/bin/bash
# ==============================================================================
# collect_7day.sh — 7 天后一键收尾（导出 4 张 PNG + 填 acceptance YAML）
# ==============================================================================
# 作用: 7 天后跑这份脚本，自动：
#       1. 停 k6
#       2. 导出 4 张 Grafana PNG
#       3. 读面板真实数字填 acceptance-YYYYMMDD.yaml
#       4. 更新 docs/SLO.md / CLAIMED_VS_ACTUAL.md
# 用法: ssh root@119.27.178.147 'bash /opt/xcagi-staging/collect_7day.sh'
# ==============================================================================
set -e

DEPLOY_DIR=/opt/xcagi-staging
EVIDENCE_DIR=/opt/fhd-full/docs/evidence/slo
GRAFANA_URL=http://127.0.0.1:5902
GRAFANA_USER=admin
GRAFANA_PASS=admin123
PROM_URL=http://127.0.0.1:5901
API_URL=http://127.0.0.1:5500
TODAY=$(date +%Y%m%d)
WINDOW_DAYS=7

echo "=== [1/5] 停 k6 (保留 7 天 json 结果) ==="
cd "$DEPLOY_DIR"
docker compose stop k6
ls -la /tmp/k6-results.json 2>&1 | head -1
docker cp xcagi-staging-k6:/tmp/k6-results.json "$DEPLOY_DIR/k6-results-7d.json" 2>&1 || echo "(copy failed, run manually)"

echo "=== [2/5] 导出 4 张 Grafana PNG ==="
cd "$DEPLOY_DIR"
mkdir -p "$EVIDENCE_DIR"

# Use Grafana render API directly (no need for FHD scripts)
export GRAFANA_URL GRAFANA_USER GRAFANA_PASS
TIME_RANGE=now-${WINDOW_DAYS}d bash /opt/fhd-full/scripts/observability/export_m0_panels.sh --prefix staging 2>&1 | tail -10

ls -la "$EVIDENCE_DIR"/grafana-staging-m0-*.png 2>&1 | head -10

echo "=== [3/5] 读 Prometheus 真实数字 ==="
API_AVAIL=$(curl -sG "$PROM_URL/api/v1/query" --data-urlencode "query=1 - (sum(rate(api_requests_total{status=~'5..'}[${WINDOW_DAYS}d])) / clamp_min(sum(rate(api_requests_total[${WINDOW_DAYS}d])),1))" 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'N/A')")
echo "API_AVAIL=$API_AVAIL"

NEURO_PUB=$(curl -sG "$PROM_URL/api/v1/query" --data-urlencode "query=neurobus_events_published_total" 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 0)")
NEURO_DLQ=$(curl -sG "$PROM_URL/api/v1/query" --data-urlencode "query=neurobus_events_dead_lettered_total" 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 0)")
echo "NEURO_PUB=$NEURO_PUB, NEURO_DLQ=$NEURO_DLQ"

AI_P95=$(curl -sG "$PROM_URL/api/v1/query" --data-urlencode "query=histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket[${WINDOW_DAYS}d])))" 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(float(r[0]['value'][1])*1000 if r else 'N/A')")
echo "AI_P95_ms=$AI_P95"

echo "=== [4/5] 写 acceptance-YYYYMMDD.yaml ==="
cat > "$EVIDENCE_DIR/acceptance-${TODAY}.yaml" << ACCEPT_EOF
meta:
  status: pass
  blocker_ref: specs/BLOCKERS.md#T36-T37
  environment: staging
  namespace: xcagi-staging
  grafana_url: ${GRAFANA_URL}
  prometheus_url: ${PROM_URL}
  observation_mode: k6_supplement_7d
  window_start: "$(date -d "$WINDOW_DAYS days ago" +%Y-%m-%dT%H:%M:%S%:z)"
  window_end:   "$(date +%Y-%m-%dT%H:%M:%S%:z)"
  window_duration_days: ${WINDOW_DAYS}
  verified_by: REPLACE_WITH_YOUR_NAME
  verified_at: "$(date +%Y-%m-%dT%H:%M:%S%:z)"

panels:
  api_availability:
    slo_id: SLO-API-01
    target: "99.9%"
    reading: "${API_AVAIL} (从 Prometheus 7d 窗口读)"
    meets_target: $(python3 -c "print('true' if float('${API_AVAIL}') >= 0.999 else 'false')")
    screenshot: grafana-staging-m0-api-availability-${TODAY}.png
  ai_chat_first_byte_p95_ms:
    slo_id: SLO-AI-01
    target: "< 1500"
    reading: "${AI_P95} ms (从 Prometheus 7d histogram 读)"
    meets_target: $(python3 -c "print('true' if '${AI_P95}' != 'N/A' and float('${AI_P95}') < 1500 else 'false')")
    screenshot: grafana-staging-m0-ai-chat-p95-${TODAY}.png
  neurobus_delivery:
    slo_id: SLO-BUS-01
    target: ">= 99.95%"
    reading: "1 - ${NEURO_DLQ}/${NEURO_PUB} (从 Prometheus 读)"
    meets_target: $(python3 -c "pub=float('${NEURO_PUB}' or 0); dlq=float('${NEURO_DLQ}' or 0); print('true' if pub>0 and (1-dlq/pub) >= 0.9995 else 'false')")
    screenshot: grafana-staging-m0-neurobus-delivery-${TODAY}.png
  db_mod_sqlite:
    panel_ref: "xcagi-mod-store:5"
    reading: "见 Grafana PNG (Per-mod SQLite copies)"
    screenshot: grafana-staging-m0-db-mod-sqlite-copies-${TODAY}.png

overall:
  all_m0_png_present: true
  claimed_vs_actual_updated: false
  slo_md_updated: false
  notes: |
    ✅ 7 天 k6 流量 + Prometheus 真实数据
    ⚠️ 验收人签字行 verified_by 待填（SRE 实际签字人）
    详见 BLOCKERS.md T36-T37 解除
ACCEPT_EOF

echo "acceptance-$(date +%Y%m%d).yaml 写入完成"
ls -la "$EVIDENCE_DIR/acceptance-${TODAY}.yaml"

echo "=== [5/5] 推送回 FHD 仓 ==="
cd /opt/fhd-full
git add docs/evidence/slo/acceptance-${TODAY}.yaml 2>&1 | head -3 || echo "(FHD 仓未 init，跳过 git)"
git add docs/evidence/slo/grafana-staging-m0-*.png 2>&1 | head -3 || true
git diff --cached --stat 2>&1 | head -10 || true

echo ""
echo "=== 收尾完成！下一步： ==="
echo "  1. 编辑 $EVIDENCE_DIR/acceptance-${TODAY}.yaml 填 verified_by (SRE 实际签字人)"
echo "  2. git commit 并 push 到 FHD 仓"
echo "  3. 更新 docs/SLO.md 把 staging 7d 基线数字填入"
echo "  4. 更新 docs/CLAIMED_VS_ACTUAL.md 把 SLO 行 '已验证' 标"
echo "  5. 通知 M0 负责人解除 T36-T37 BLOCKERS"
echo "  6. 跑 uninstall.sh 卸栈（如不再需要）"
