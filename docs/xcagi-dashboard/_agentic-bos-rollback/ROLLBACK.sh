#!/usr/bin/env bash
# Agentic Business OS 一键回滚 — 还原到改动前的原始版本
# 用法：bash docs/xcagi-dashboard/_agentic-bos-rollback/ROLLBACK.sh
# 原理：这些 dashboard 文件不在 git 仓库内，故用 *.orig 快照（改动前原始版）覆盖回 live 文件。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$(cd "$HERE/.." && pwd)"               # docs/xcagi-dashboard
ROOT="$(cd "$HERE/../../.." && pwd)"          # 工作区根（HTML 在此）

# 格式： "<.orig 基名>|<还原目标绝对/相对路径>"
FILES=(
  "emp-wf-radial-graph.js|$DST/emp-wf-radial-graph.js"
  "event-merged-arch-graph.js|$DST/event-merged-arch-graph.js"
  "daily_digest_node_employees.json|$DST/daily_digest_node_employees.json"
  "XCAGI-Full-Pipeline.html|$ROOT/XCAGI-Full-Pipeline.html"
)

echo "== Agentic Business OS 回滚 =="
echo "源（原始快照）: $HERE"
echo "目标（live）  : $DST"
echo

# 回滚前再存一份当前（含 Agentic BOS 改动）版本，避免误操作不可逆
TS="$(date +%Y%m%d-%H%M%S)"
REDO="$HERE/_pre-rollback-$TS"
mkdir -p "$REDO"

for entry in "${FILES[@]}"; do
  base="${entry%%|*}"
  target="${entry##*|}"
  if [[ -f "$target" ]]; then
    cp "$target" "$REDO/$base"
  fi
  cp "$HERE/$base.orig" "$target"
  echo "restored: $base -> $target"
done

echo
echo "已还原到改动前原始版本。"
echo "当前(含改动)版本已另存：$REDO （如需重新前进可从此恢复）"
