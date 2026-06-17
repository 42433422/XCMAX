#!/usr/bin/env bash
# FlClash / mihomo 自动测速换节点（Selector 分组）+ 代理健康巡检
# 用法:
#   bash flclash-auto-switch.sh          # 测速并切换到各 Selector 组最快节点
#   bash flclash-auto-switch.sh --watch  # 每 5 分钟巡检，失败或变慢时重选
#   bash flclash-auto-switch.sh --health # 仅健康检查，不切换
set -euo pipefail

API_BASE="${FLCLASH_API:-http://127.0.0.1:9090}"
PROXY="http://127.0.0.1:7890"
DELAY_URL="${FLCLASH_DELAY_URL:-http://www.gstatic.com/generate_204}"
DELAY_TIMEOUT_MS="${FLCLASH_DELAY_TIMEOUT_MS:-5000}"
WATCH_INTERVAL_SEC="${FLCLASH_WATCH_INTERVAL_SEC:-300}"
# 逗号分隔的 Selector 组名；留空则自动发现所有 Selector（跳过 GLOBAL / Manual Select）
SELECTOR_GROUPS="${FLCLASH_SELECTOR_GROUPS:-🤖 ChatGPT Group}"

urlenc() { python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }

api_get() { curl -sS --connect-timeout 3 "${API_BASE}$1"; }

api_put_proxy() {
  local group="$1" node="$2"
  local enc
  enc="$(urlenc "$group")"
  curl -sS --connect-timeout 5 -X PUT \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'name': sys.argv[1]}))" "$node")" \
    "${API_BASE}/proxies/${enc}" >/dev/null
}

flclash_ready() {
  curl -sS --connect-timeout 2 "${API_BASE}/" >/dev/null 2>&1
}

proxy_ready() {
  curl -sS --connect-timeout 2 -o /dev/null "${PROXY}" 2>/dev/null
}

health_ok() {
  local url code
  for url in "https://api2.cursor.sh" "https://api.github.com"; do
    code="$(curl -sS --connect-timeout 8 -x "${PROXY}" -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")"
    if [[ "$code" == "000" || "$code" =~ ^5 ]]; then
      echo "unhealthy: $url -> $code"
      return 1
    fi
  done
  return 0
}

discover_selector_groups() {
  api_get "/proxies" | python3 -c "
import json, sys, os
skip = {'GLOBAL', '❇️Manual Select', '🌐 Auto Select'}
raw = os.environ.get('SELECTOR_GROUPS', '').strip()
if raw:
    for g in raw.split(','):
        g = g.strip()
        if g:
            print(g)
    raise SystemExit(0)
data = json.load(sys.stdin).get('proxies', {})
for name, meta in data.items():
    if meta.get('type') == 'Selector' and name not in skip:
        print(name)
"
}

best_node_for_group() {
  local group="$1"
  local enc delays
  enc="$(urlenc "$group")"
  delays="$(curl -sS --connect-timeout 10 -G \
    "${API_BASE}/group/${enc}/delay" \
    --data-urlencode "timeout=${DELAY_TIMEOUT_MS}" \
    --data-urlencode "url=${DELAY_URL}" 2>/dev/null || true)"
  python3 -c "
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(1)
data = json.loads(raw)
pairs = [(k, v) for k, v in data.items() if isinstance(v, int)]
if not pairs:
    raise SystemExit(1)
pairs.sort(key=lambda x: x[1])
best, delay = pairs[0]
print(f'{best}\t{delay}')
" <<<"$delays"
}

switch_group_to_best() {
  local group="$1"
  local current best delay line
  current="$(api_get "/proxies" | python3 -c "
import json, sys
g = sys.argv[1]
print(json.load(sys.stdin)['proxies'][g].get('now', ''))
" "$group" 2>/dev/null || true)"
  line="$(best_node_for_group "$group" || true)"
  if [[ -z "$line" ]]; then
    echo "[skip] $group: 测速失败" >&2
    return 1
  fi
  best="${line%%$'\t'*}"
  delay="${line##*$'\t'}"
  if [[ "$current" == "$best" ]]; then
    echo "[ok] $group: 保持 $best (${delay}ms)"
    return 0
  fi
  api_put_proxy "$group" "$best"
  echo "[switch] $group: $current -> $best (${delay}ms)"
}

run_once() {
  if ! flclash_ready; then
    echo "FlClash API 未就绪: ${API_BASE}" >&2
    exit 1
  fi
  if ! proxy_ready; then
    echo "代理端口未监听: ${PROXY}" >&2
    exit 1
  fi

  local group
  while IFS= read -r group; do
    [[ -n "$group" ]] || continue
    switch_group_to_best "$group" || true
  done < <(discover_selector_groups)

  # URLTest 组（如 🌐 Auto Select）由内核自动挑节点，仅打印当前选中
  api_get "/proxies" | python3 -c "
import json, sys
p = json.load(sys.stdin)['proxies']
for name in ('GLOBAL', '🌐 Auto Select'):
    if name in p:
        print(f'[info] {name}: {p[name].get(\"now\", \"?\")} ({p[name].get(\"type\", \"\")})')
"
}

mode="${1:-}"

case "$mode" in
  --health)
    if health_ok; then
      echo "代理健康检查通过"
      exit 0
    fi
    exit 1
    ;;
  --watch)
    echo "FlClash 自动换节点守护启动，间隔 ${WATCH_INTERVAL_SEC}s"
    while true; do
      if health_ok 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] 健康"
      else
        echo "[$(date '+%H:%M:%S')] 不健康，触发重选节点"
        run_once || true
      fi
      sleep "$WATCH_INTERVAL_SEC"
    done
    ;;
  ""|--once)
    run_once
    ;;
  -h|--help)
    sed -n '2,8p' "$0"
    ;;
  *)
    echo "未知参数: $mode （可用 --once / --watch / --health）" >&2
    exit 2
    ;;
esac
