#!/usr/bin/env bash
# 扫描 monorepo 中跨组件的相对路径引用，输出潜在的"拆仓后会断链"清单。
# 仅做扫描，不修改任何文件。
set -euo pipefail

echo "[info] 扫描跨组件相对引用..."

# 1) market → modstore_server（前后端耦合；拆仓后通过 API 契约解耦）
echo
echo "--- market → modstore_server 源码引用 ---"
rg -l --hidden -g '!node_modules' -g '!dist' -g '!.venv' \
  "MODstore_deploy/modstore_server" MODstore_deploy/market 2>/dev/null || true

# 2) modstore_server → market（一般不应存在）
echo
echo "--- modstore_server → market 源码引用 ---"
rg -l --hidden -g '!node_modules' \
  "MODstore_deploy/market" MODstore_deploy/modstore_server 2>/dev/null || true

# 3) java_payment_service → modstore_server（应仅通过 HTTP webhook）
echo
echo "--- java_payment_service → modstore_server ---"
rg -l "MODstore_deploy/modstore_server" MODstore_deploy/java_payment_service 2>/dev/null || true

# 4) vibe-coding → eskill-prototype（文档明确说会 sync）
echo
echo "--- vibe-coding → eskill-prototype ---"
rg -l "eskill-prototype" vibe-coding 2>/dev/null || true

# 5) 根静态页 → MODstore_deploy（应只通过 /market/ HTTP 入口）
echo
echo "--- 根营销页 → MODstore_deploy ---"
rg -l --glob '*.html' "MODstore_deploy" . 2>/dev/null | grep -v 'MODstore_deploy/' || true

echo
echo "[ok] 扫描完成。以上清单在拆仓前需要按组件契约重写，避免断链。"
