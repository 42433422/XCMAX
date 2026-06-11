#!/bin/bash
# 将仓库 deploy/nginx/snippets 同步到 CVM，并合并 MODstore/COS/官网静态规则到 xiu-ci.com.conf
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SNIP_SRC="$REPO_ROOT/deploy/nginx/snippets"
SNIP_DST="/etc/nginx/snippets"
CONF="/etc/nginx/conf.d/xiu-ci.com.conf"

mkdir -p "$SNIP_DST"
for f in market-static.inc.conf corp-main-styles.inc.conf xcagi-cos-alias.inc.conf marketing-site-static.inc.conf; do
  cp -a "$SNIP_SRC/$f" "$SNIP_DST/$f"
  echo "synced $f"
done

cp -a "$CONF" "${CONF}.bak.$(date +%Y%m%d%H%M%S)"

python3 << 'PY'
import re
from pathlib import Path

conf = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
t = conf.read_text(encoding="utf-8")

# 删除危险的整站 market SPA 回退
t = re.sub(
    r"\n    # MODstore 仅通过 /market/.*?\n",
    "\n",
    t,
    flags=re.DOTALL,
)
t = re.sub(
    r"\n    # MODstore 前端根路径\n    location / \{\n        root /root/成都修茈科技有限公司/MODstore_deploy/market/dist;\n        index index\.html;\n        try_files \$uri \$uri/ /index\.html;\n        add_header Cache-Control \"no-cache\";\n    \}\n",
    "\n",
    t,
    count=1,
)

# 去掉旧版重复的 market / COS / main 块（由 include 替代）
blocks = [
    r"\n    # Vite 偶发解析出 /market/assets/assets/.*?location \^~ /market/assets/ \{[^}]+\}\n",
    r"\n    # 旧缓存页请求 /market/main\.js.*?add_header Cache-Control \"no-cache, must-revalidate\" always;\n    \}\n",
    r"\n    # market 静态 chunk：.*?location \^~ /market/assets/ \{[^}]+\}\n",
    r"\n    location /market/ \{\n        alias /root/成都修茈科技有限公司/MODstore_deploy/market/dist/;\n        try_files \$uri \$uri/ /market/index\.html;[^}]+\}\n",
    r"\n    # 避免 /market/main\.js.*?location = /market/styles\.css \{[^}]+\}\n",
    r"\n    ## XCAGI_COS_ALIAS_BEGIN.*?## XCAGI_RELEASES_END\n",
]
for pat in blocks:
    t = re.sub(pat, "\n", t, flags=re.DOTALL)

marker = "    ## CORP_SITE_END"
includes = """
    include /etc/nginx/snippets/marketing-site-static.inc.conf;
    include /etc/nginx/snippets/corp-main-styles.inc.conf;
    include /etc/nginx/snippets/xcagi-cos-alias.inc.conf;
    include /etc/nginx/snippets/market-static.inc.conf;
"""
if "snippets/market-static.inc.conf" not in t:
    t = t.replace(marker, marker + includes)

conf.write_text(t, encoding="utf-8")
print("merged includes into xiu-ci.com.conf")
PY

nginx -t
nginx -s reload
echo "nginx reload ok"
