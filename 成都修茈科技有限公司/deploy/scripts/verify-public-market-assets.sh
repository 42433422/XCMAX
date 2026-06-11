#!/usr/bin/env bash
# 公网验收：market JS 必须为 application/javascript，且非 EdgeOne HTML 回退
set -euo pipefail
BASE="${1:-https://xiu-ci.com}"
paths=(
  "/market/assets/index-t4QjOg3z.js"
  "/market/assets/WorkbenchView-B7VzJfNL.js"
  "/market/assets/WorkbenchHomeView-C0VhrLLz.js"
)
for p in "${paths[@]}"; do
  url="${BASE}${p}"
  echo "== $url"
  headers=$(curl -skI --max-time 20 "$url" | tr -d '\r')
  server=$(echo "$headers" | awk -F': ' 'tolower($1)=="server"{print $2; exit}')
  ct=$(echo "$headers" | awk -F': ' 'tolower($1)=="content-type"{print $2; exit}')
  body=$(curl -sk --max-time 20 "$url" | head -c 20)
  echo "   server=$server ct=$ct body=$body"
  echo "$server" | grep -qi edgeone-pages && { echo "FAIL: still edgeone-pages — see deploy/docs/runbooks/dns-edgeone-to-cvm.md"; exit 1; }
  echo "$ct" | grep -qi javascript || { echo "FAIL: not javascript"; exit 1; }
  echo "$body" | grep -q '^<!DOCTYPE' && { echo "FAIL: HTML body"; exit 1; }
done
echo "OK: public market assets are JS"
