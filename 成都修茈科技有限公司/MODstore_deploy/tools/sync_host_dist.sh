#!/bin/bash
set -e
DIST='/root/成都修茈科技有限公司/MODstore_deploy/market/dist'
mkdir -p "$DIST"
tar -xzf /tmp/market_dist.tgz -C "$DIST"
echo "HOST_INDEX:"
grep script "$DIST/index.html"
echo "---PUBLIC---"
curl -sI https://xiu-ci.com/market/assets/index-0o-4boUO.js | head -2
curl -sI https://xiu-ci.com/market/assets/WorkbenchHomeView-DPR5nWNH.js | head -2
