#!/usr/bin/env bash
# 只把我的 GOV 改动暂存并提交（不带 621、不碰 VERSION.md、不 push）。
# 用 git apply --cached 把 (.orig -> live) 的差异 patch 进 index（index=HEAD）。
set -uo pipefail

FHD="/Users/a4243342/Desktop/XCMAX/FHD"
BK="$FHD/../docs/xcagi-dashboard/_agentic-bos-rollback/backend"
cd "$FHD"

PRE="$BK/_pre-commit-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$PRE"
git rev-parse HEAD > "$PRE/BASELINE.txt"
echo "baseline HEAD: $(cat "$PRE/BASELINE.txt")"

MAP=(
  "operations_line_bridge.py|app/services/operations_line_bridge.py"
  "cs_operations.py|app/infrastructure/gateways/cs_operations.py"
  "operations_app_service.py|app/application/operations_app_service.py"
  "operations_line_api.py|app/fastapi_routes/operations_line_api.py"
)

allok=1
for m in "${MAP[@]}"; do
  base="${m%%|*}"; P="${m##*|}"
  cp "$P" "$PRE/$base.now"
  git diff --no-index --src-prefix=a/ --dst-prefix=b/ "$BK/$base.orig" "$P" > "$PRE/$base.patch"
  # 重写 patch 头的 ---/+++ 为真实仓库相对路径
  sed -i '' -E "s#^--- a/.*#--- a/$P#; s#^\+\+\+ b/.*#+++ b/$P#" "$PRE/$base.patch"
  if git apply --cached --check "$PRE/$base.patch" 2>"$PRE/$base.err"; then
    echo "CHECK OK   $P"
  else
    echo "CHECK FAIL $P -> $(cat "$PRE/$base.err")"
    allok=0
  fi
done

echo "ALL_CHECK_OK=$allok"
echo "PRE=$PRE"
