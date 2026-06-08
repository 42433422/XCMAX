#!/usr/bin/env bash
# 部署全景仪表盘到公网 CVM，供 MODstore「运维终端」iframe 嵌入。
#
# 用法（XCMAX 根目录）:
#   DEPLOY_SSH_PASSWORD='…' bash FHD/scripts/dev/deploy_xcagi_dashboard_server.sh
#
# 可选:
#   XCMAX_REMOTE_HOST=119.27.178.147
#   XCMAX_DASHBOARD_REMOTE_DIR=/root/XCMAX
#   MODSTORE_MARKET_DIST=/root/成都修茈科技有限公司/MODstore_deploy/market/dist
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
HOST="${XCMAX_REMOTE_HOST:-119.27.178.147}"
USER="${DEPLOY_SSH_USER:-root}"
PORT="${DEPLOY_SSH_PORT:-22}"
REMOTE_DIR="${XCMAX_DASHBOARD_REMOTE_DIR:-/root/XCMAX}"
MARKET_DIST="${MODSTORE_MARKET_DIST:-/root/成都修茈科技有限公司/MODstore_deploy/market/dist}"
TAR="/tmp/xcmax-dashboard-deploy_$$.tar.gz"

log() { printf '[deploy-dashboard] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -n "${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}" ]] || fail "请设置 DEPLOY_SSH_PASSWORD"

[[ -f "${XCMAX_ROOT}/XCAGI-Full-Pipeline.html" ]] || fail "缺少 ${XCMAX_ROOT}/XCAGI-Full-Pipeline.html"

log "打包 dashboard 静态…"
tar -czf "${TAR}" -C "${XCMAX_ROOT}" \
  XCAGI-Full-Pipeline.html \
  docs/xcagi-dashboard

trap 'rm -f "${TAR}"' EXIT

REMOTE_SCRIPT=$(cat <<REMOTE_EOF
set -e
REMOTE_DIR="__REMOTE_DIR__"
MARKET_DIST="__MARKET_DIST__"
mkdir -p "\${REMOTE_DIR}"
tar -xzf /tmp/xcmax-dashboard-deploy.tar.gz -C "\${REMOTE_DIR}"
chmod -R a+rX "\${REMOTE_DIR}/docs" "\${REMOTE_DIR}/XCAGI-Full-Pipeline.html" 2>/dev/null || true

SNIP=/etc/nginx/snippets/xcmax-dashboard.inc.conf
cat > "\${SNIP}" <<'NGINX'
# XCMAX 全景仪表盘 — 运维终端 iframe（须在市场 SPA location / 之前 include）
location = /XCAGI-Full-Pipeline.html {
    return 302 /xcmax-dashboard/XCAGI-Full-Pipeline.html\$is_args\$args;
}
location ^~ /xcmax-dashboard/ {
    alias __REMOTE_DIR__/;
    add_header Cache-Control "no-cache, must-revalidate" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
}
NGINX
sed -i "s|__REMOTE_DIR__|\${REMOTE_DIR}|g" "\${SNIP}"

CONF=/etc/nginx/conf.d/xiu-ci.com.conf
if ! grep -q 'xcmax-dashboard.inc.conf' "\${CONF}"; then
  sed -i '/## CORP_SITE_HOME_BEGIN/i\\    include /etc/nginx/snippets/xcmax-dashboard.inc.conf;\\n' "\${CONF}"
fi

nginx -t
systemctl reload nginx

# 修补已部署 market 包里的旧 iframe URL（免全量 npm build）
if [[ -d "\${MARKET_DIST}/assets" ]]; then
  find "\${MARKET_DIST}/assets" -name '*.js' -type f -print0 2>/dev/null | while IFS= read -r -d '' f; do
    if grep -q 'XCAGI-Full-Pipeline.html' "\$f" 2>/dev/null; then
      sed -i 's|\${window.location.origin.replace(/\\/\$/,"")}/XCAGI-Full-Pipeline.html#aibiz|\${window.location.origin.replace(/\\/\$/,"")}/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz|g' "\$f" 2>/dev/null || true
      sed -i 's|/XCAGI-Full-Pipeline.html#aibiz|/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz|g' "\$f"
      sed -i 's|http://127.0.0.1:8765/XCAGI-Full-Pipeline.html#aibiz|/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz|g' "\$f"
      sed -i 's|Full-Pipeline.html?embed=shell#aibiz|xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz|g' "\$f"
    fi
  done
fi

echo "[ok] dashboard at \${REMOTE_DIR}"
curl -sf -m 8 -o /dev/null -w "pipeline_http=%{http_code}\n" \
  -H 'Host: xiu-ci.com' https://127.0.0.1/xcmax-dashboard/XCAGI-Full-Pipeline.html -k || true
head -c 80 "\${REMOTE_DIR}/XCAGI-Full-Pipeline.html" | tr '\\n' ' '; echo
REMOTE_EOF
)
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_DIR__/${REMOTE_DIR}}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__MARKET_DIST__/${MARKET_DIST}}"

/usr/bin/expect <<EXPECT_EOF
set timeout 300
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

scp_up {${TAR}} /tmp/xcmax-dashboard-deploy.tar.gz
ssh_run {${REMOTE_SCRIPT}}
EXPECT_EOF

log "完成。验证: curl -sI https://xiu-ci.com/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz"
log "运维终端: https://xiu-ci.com/market/admin/ops-terminal"
