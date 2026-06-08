#!/usr/bin/env bash
# Agentic Business OS 后端 (FASTGATE + GOV) 一键回滚
# 用法：bash docs/xcagi-dashboard/_agentic-bos-rollback/backend/ROLLBACK_BACKEND.sh
# 背景：FHD 是 git 仓库但有大量未提交改动（无法只 revert 本次），sibling 栈非 git，
#       故用 *.orig 逐文件快照还原 + 删除新增文件。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"   # 工作区根
MOD="$ROOT/成都修茈科技有限公司/MODstore_deploy/modstore_server"

# "<.orig 基名>|<还原目标绝对路径>"
FILES=(
  "operations_line_bridge.py|$ROOT/FHD/app/services/operations_line_bridge.py"
  "cs_operations.py|$ROOT/FHD/app/infrastructure/gateways/cs_operations.py"
  "operations_app_service.py|$ROOT/FHD/app/application/operations_app_service.py"
  "operations_line_api.py|$ROOT/FHD/app/fastapi_routes/operations_line_api.py"
  "digest_daily_line_chain.py|$MOD/digest_daily_line_chain.py"
)
# 新增文件（回滚即删除）
NEW_FILES=(
  "$MOD/installer_fastgate.py"
)

TS="$(date +%Y%m%d-%H%M%S)"
REDO="$HERE/_pre-rollback-$TS"; mkdir -p "$REDO"

echo "== Agentic BOS 后端回滚 (ROOT=$ROOT) =="
for entry in "${FILES[@]}"; do
  base="${entry%%|*}"; target="${entry##*|}"
  [[ -f "$target" ]] && cp "$target" "$REDO/$base"
  cp "$HERE/$base.orig" "$target"
  echo "restored: $base -> $target"
done
for nf in "${NEW_FILES[@]}"; do
  if [[ -f "$nf" ]]; then
    cp "$nf" "$REDO/$(basename "$nf")"
    rm -f "$nf"
    echo "removed (new): $nf"
  fi
done
echo "完成。当前(含改动)版本已另存：$REDO"
