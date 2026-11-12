#!/bin/bash
# 部署 / Nginx / market / COS 变更后执行；失败时 exit 1
set -euo pipefail

REPO="/root/成都修茈科技有限公司"
DIST="$REPO/MODstore_deploy/market/dist"
INDEX="$DIST/index.html"
CHUNK="index-t4QjOg3z.js"
HOST="${POST_DEPLOY_HOST:-127.0.0.1}"
SNI="${POST_DEPLOY_SNI:-xiu-ci.com}"
PUBLIC_BASE="${POST_DEPLOY_PUBLIC_BASE:-https://xiu-ci.com}"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK: $*"; }

echo "=== post-deploy-check $(date -Iseconds) ==="

# 1) market 入口必须是 Vue，禁止官网 index 覆盖
grep -q "$CHUNK" "$INDEX" || fail "market/dist/index.html missing $CHUNK (corp index overwrite?)"
if grep -q 'site-header' "$INDEX"; then
  fail "market/dist/index.html looks like corp site (site-header)"
fi
ok "market index references $CHUNK"

test -f "$DIST/assets/$CHUNK" || fail "missing chunk $DIST/assets/$CHUNK"
ok "chunk file exists"

for lazy in WorkbenchView-B7VzJfNL.js WorkbenchHomeView-C0VhrLLz.js MessageBody-C_yewlj6.js; do
  test -f "$DIST/assets/$lazy" || fail "missing lazy chunk $DIST/assets/$lazy"
done
ok "lazy chunks on disk"

# 2) 本机 HTTPS Content-Type（勿返回 text/html 给 .js）
check_ct() {
  local path="$1"
  local expect="$2"
  local ct
  ct=$(curl -skI -H "Host: $SNI" "https://${HOST}${path}" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-type"{print $2; exit}')
  echo "local $path -> ${ct:-<none>}"
  echo "$ct" | grep -qi "$expect" || fail "local $path Content-Type expected ~$expect got: ${ct:-none}"
}

check_ct "/main.js" "javascript"
check_ct "/market/assets/$CHUNK" "javascript"
check_ct "/market/" "html"

# 2b) 公网：DNS 若仍指向 EdgeOne Pages，lazy chunk 会返回 HTML
check_public_js() {
  local path="$1"
  local url="${PUBLIC_BASE}${path}"
  local headers body_prefix server ct
  headers=$(curl -skI --max-time 25 "$url" | tr -d '\r')
  server=$(echo "$headers" | awk -F': ' 'tolower($1)=="server"{print $2; exit}')
  ct=$(echo "$headers" | awk -F': ' 'tolower($1)=="content-type"{print $2; exit}')
  body_prefix=$(curl -sk --max-time 25 "$url" | head -c 16 || true)
  echo "public $path -> server=${server:-?} ct=${ct:-?} body=${body_prefix}"
  if echo "$server" | grep -qi 'edgeone-pages'; then
    fail "public $path still served by edgeone-pages; fix DNS per deploy/docs/runbooks/dns-edgeone-to-cvm.md"
  fi
  echo "$ct" | grep -qi 'javascript' || fail "public $path not application/javascript (got ${ct:-none})"
  if echo "$body_prefix" | grep -q '^<!DOCTYPE'; then
    fail "public $path body is HTML not JS"
  fi
}

if [[ "${POST_DEPLOY_SKIP_PUBLIC:-}" != "1" ]]; then
  check_public_js "/market/assets/$CHUNK"
  check_public_js "/market/assets/WorkbenchView-B7VzJfNL.js"
  ok "public market assets are real JS (not EdgeOne HTML fallback)"
fi

# 3) COS 安装包目录
EXE="/var/www/update/releases/stable/personal/XCAGI-Personal-Setup-8.0.0-x64.exe"
test -f "$EXE" || fail "missing $EXE"
ok "COS/stable exe present"

# 4) 依赖服务
systemctl is-active --quiet modstore && ok "modstore active" || fail "modstore not active"
docker ps --format '{{.Names}}' 2>/dev/null | grep -qE 'postgres|rabbitmq' || echo "WARN: postgres/rabbitmq container names not found (optional)"

echo "=== all checks passed ==="
