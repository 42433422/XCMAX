#!/usr/bin/env bash
# 公网运维终端 · AI 业务数据：部署 aibiz API 到 fhd-full (:5100) + 同步 surface-audit 缓存 + nginx 路由。
#
# 用法:
#   DEPLOY_SSH_PASSWORD='…' bash FHD/scripts/dev/deploy_aibiz_ops_terminal_server.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
HOST="${XCMAX_REMOTE_HOST:-119.27.178.147}"
USER="${DEPLOY_SSH_USER:-root}"
PORT="${DEPLOY_SSH_PORT:-22}"
FHD_REMOTE="${FHD_REMOTE_ROOT:-/opt/fhd-full}"
TAR_CODE="/tmp/aibiz-code-deploy_$$.tar.gz"
TAR_DATA="/tmp/aibiz-surface-deploy_$$.tar.gz"

log() { printf '[deploy-aibiz] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -n "${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}" ]] || fail "请设置 DEPLOY_SSH_PASSWORD"

log "打包 aibiz 后端代码…"
tar -czf "${TAR_CODE}" -C "${FHD_ROOT}" \
  app/fastapi_routes/aibiz_terminal_api.py \
  app/application/aibiz_web_terminal_service.py \
  app/application/surface_audit_service.py \
  app/application/surface_audit_demo_account.py \
  app/application/modstore_local_client.py \
  app/services/operations_line_bridge.py \
  config/surface_audit_pages.json \
  config/surface_audit_demo_account.json

log "打包 surface-audit 缓存（PNG + JSON）…"
tar -czf "${TAR_DATA}" -C "${FHD_ROOT}" data/surface_audit

trap 'rm -f "${TAR_CODE}" "${TAR_DATA}"' EXIT

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -e
FHD="__FHD_REMOTE__"
mkdir -p "${FHD}/app/fastapi_routes" "${FHD}/app/application" "${FHD}/app/services" "${FHD}/config" "${FHD}/data"
tar -xzf /tmp/aibiz-code-deploy.tar.gz -C "${FHD}"
tar -xzf /tmp/aibiz-surface-deploy.tar.gz -C "${FHD}"

# 注册 aibiz 路由（若尚未注册）
python3 <<'PY'
from pathlib import Path
p = Path("__FHD_REMOTE__/app/fastapi_routes/__init__.py")
text = p.read_text(encoding="utf-8")
block = '''
    try:
        from app.fastapi_routes.aibiz_terminal_api import router as aibiz_terminal_router

        app.include_router(aibiz_terminal_router)
        logger.info("Registered aibiz_terminal_router (/api/xcmax/aibiz/*)")
    except Exception as e:
        logger.warning("aibiz_terminal router not available: %s", e)
'''
if "aibiz_terminal_api" not in text:
    anchor = 'logger.warning("xcmax_admin router not available: %s", e)'
    if anchor not in text:
        raise SystemExit("xcmax_admin anchor not found in __init__.py")
    text = text.replace(anchor, anchor + "\n" + block, 1)
    p.write_text(text, encoding="utf-8")
    print("[ok] patched __init__.py")
else:
    print("[skip] aibiz already in __init__.py")
PY

ENV=/root/fhd-full.env
touch "${ENV}"
upsert() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "${ENV}" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "${ENV}"
  else
    echo "${k}=${v}" >> "${ENV}"
  fi
}
upsert XCAGI_AIBIZ_MARKET_USER admin
upsert XCAGI_AIBIZ_MARKET_PASSWORD admin123
upsert XCAGI_MARKET_BASE_URL https://xiu-ci.com
upsert XCMAX_MONOREPO_ROOT /root/XCMAX
upsert XCAGI_SURFACE_AUDIT_LOCAL 1

# nginx: aibiz API -> fhd-full :5100（须在 /api/xcmax/ -> 5099 之前）
SNIP=/etc/nginx/snippets/xcmax-aibiz-api.inc.conf
cat > "${SNIP}" <<'NGINX'
# AI 业务数据 Tab · 三端终端（fhd-full，非 sandbox 5099）
location ^~ /api/xcmax/aibiz/ {
    proxy_pass http://127.0.0.1:5100;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_buffering off;
    proxy_connect_timeout 15s;
    proxy_send_timeout 3600s;
    proxy_read_timeout 3600s;
    client_max_body_size 100m;
}
NGINX

CONF=/etc/nginx/conf.d/xiu-ci.com.conf
if ! grep -q 'xcmax-aibiz-api.inc.conf' "${CONF}"; then
  sed -i '/location \^~ \/api\/xcmax\//i\    include /etc/nginx/snippets/xcmax-aibiz-api.inc.conf;\n' "${CONF}"
fi

nginx -t
systemctl reload nginx
systemctl restart fhd-full
sleep 3

echo "=== local probe ==="
curl -sf -m 20 http://127.0.0.1:5100/api/xcmax/aibiz/web-terminal?refresh=0 | python3 -c "
import sys,json
d=json.load(sys.stdin)
data=d.get('data') or {}
pages=((data.get('surface_audit') or {}).get('pages') or [])
print('5100 success', d.get('success'), 'pages', len(pages), 'note', (data.get('surface_audit_note') or '')[:60])
" || echo "5100 probe failed"

curl -sf -m 20 -H 'Host: xiu-ci.com' http://127.0.0.1/api/xcmax/aibiz/web-terminal?refresh=0 | python3 -c "
import sys,json
d=json.load(sys.stdin)
data=d.get('data') or {}
pages=((data.get('surface_audit') or {}).get('pages') or [])
print('nginx success', d.get('success'), 'sandbox', d.get('sandbox'), 'pages', len(pages))
" || echo "nginx probe failed"
REMOTE_EOF
)
REMOTE_SCRIPT="${REMOTE_SCRIPT//__FHD_REMOTE__/${FHD_REMOTE}}"

/usr/bin/expect <<EXPECT_EOF
set timeout 600
set pw \$env(DEPLOY_SSH_PASSWORD)
if {![info exists env(DEPLOY_SSH_PASSWORD)]} { set pw \$env(DEPLOY_PW) }

proc scp_up {local remote} {
  global pw
  spawn scp -o StrictHostKeyChecking=no -P ${PORT} \$local ${USER}@${HOST}:\$remote
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    eof {}
  }
  catch wait result
  if {[lindex \$result 3] != 0} { exit [lindex \$result 3] }
}

proc ssh_run {cmd} {
  global pw
  spawn ssh -o StrictHostKeyChecking=no -p ${PORT} ${USER}@${HOST} \$cmd
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    eof {}
  }
  catch wait result
  exit [lindex \$result 3]
}

scp_up {${TAR_CODE}} /tmp/aibiz-code-deploy.tar.gz
scp_up {${TAR_DATA}} /tmp/aibiz-surface-deploy.tar.gz
ssh_run {${REMOTE_SCRIPT}}
EXPECT_EOF

log "完成。请硬刷新 https://xiu-ci.com/market/admin/ops-terminal"
