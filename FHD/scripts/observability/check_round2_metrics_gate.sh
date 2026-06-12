#!/usr/bin/env bash
# 48h gate: round-2 k6 must produce login + chat first-byte samples.
# Usage:
#   PROMETHEUS_URL=http://119.27.178.147:30090 bash scripts/observability/check_round2_metrics_gate.sh
set -euo pipefail

PROM="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
MIN_LOGIN_1H="${MIN_LOGIN_INCREASE_1H:-10}"
MIN_CHAT_1H="${MIN_CHAT_INCREASE_1H:-10}"

log() { printf '[round2-gate] %s\n' "$*"; }

query() {
  curl -sS -m 30 -G "${PROM}/api/v1/query" --data-urlencode "query=$1" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '0')"
}

login_1h="$(query 'sum(increase(api_requests_total{endpoint="/api/auth/login"}[1h]))')"
chat_1h="$(query 'sum(increase(chat_stream_first_byte_seconds_count[1h]))')"
health_1h="$(query 'sum(increase(api_requests_total{endpoint="/api/health"}[1h]))')"

log "1h increase: login=${login_1h} chat_first_byte=${chat_1h} health=${health_1h}"

fail=0
python3 - <<PY
login = float("${login_1h}")
chat = float("${chat_1h}")
health = float("${health_1h}")
min_login = float("${MIN_LOGIN_1H}")
min_chat = float("${MIN_CHAT_1H}")
if login < min_login:
    print(f"FAIL login 1h increase {login} < {min_login}")
    exit(1)
if chat < min_chat:
    print(f"FAIL chat_stream_first_byte 1h increase {chat} < {min_chat}")
    exit(1)
if health < 1:
    print(f"FAIL health 1h increase {health} < 1")
    exit(1)
print("PASS round-2 metrics gate")
PY || fail=1

exit "${fail}"
