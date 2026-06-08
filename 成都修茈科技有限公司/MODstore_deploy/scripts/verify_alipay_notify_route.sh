#!/usr/bin/env bash
# 验证公网支付宝 notify 路径可达（切换前/后各跑一次）
# 用法：NOTIFY_URL=https://xiu-ci.com/api/payment/notify/alipay ./scripts/verify_alipay_notify_route.sh
set -euo pipefail

URL="${NOTIFY_URL:-https://xiu-ci.com/api/payment/notify/alipay}"
echo "POST $URL (empty body — expect 4xx/fail text, not 502)"
code="$(curl -sS -o /tmp/notify_probe.txt -w '%{http_code}' -X POST "$URL" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'out_trade_no=probe&trade_status=TRADE_SUCCESS' || true)"
echo "HTTP $code"
head -c 200 /tmp/notify_probe.txt
echo ""
if [[ "$code" == "502" || "$code" == "503" ]]; then
  echo "FAIL: upstream unreachable — fix Nginx/Java before PAYMENT_BACKEND=java"
  exit 1
fi
echo "OK: path reachable (signature will fail on probe body — expected)"
