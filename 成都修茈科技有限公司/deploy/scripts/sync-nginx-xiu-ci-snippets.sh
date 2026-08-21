#!/bin/bash
# 将仓库 deploy/nginx/snippets 同步到 CVM，并合并 MODstore/COS/官网静态规则到 xiu-ci.com.conf
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SNIP_SRC="$REPO_ROOT/deploy/nginx/snippets"
SNIP_DST="/etc/nginx/snippets"
CONF="/etc/nginx/conf.d/xiu-ci.com.conf"

mkdir -p "$SNIP_DST"
for f in market-static.inc.conf corp-main-styles.inc.conf xcagi-cos-alias.inc.conf marketing-site-static.inc.conf founder-autonomy-admin.inc.conf; do
  cp -a "$SNIP_SRC/$f" "$SNIP_DST/$f"
  echo "synced $f"
done

cp -a "$CONF" "${CONF}.bak.$(date +%Y%m%d%H%M%S)"
python3 "$REPO_ROOT/deploy/scripts/merge-nginx-xiu-ci-snippets.py" "$CONF"

if ! nginx -t; then
  echo "[err] merged nginx configuration is invalid; managed include context follows"
  grep -n -B 8 -A 8 '/etc/nginx/snippets/.*\.inc\.conf' "$CONF" || true
  exit 1
fi
nginx -s reload
echo "nginx reload ok"
