#!/usr/bin/env bash
# 从 git 索引中移除已经被提交的运行期产物（outbox / webhook / payment_orders 等）。
# 文件仍保留在工作树（便于临时排障），但会从 git 中删除。
#
# 使用：
#   bash scripts/cleanup-committed-runtime-artifacts.sh        # 仅预览将要 rm 的文件
#   APPLY=1 bash scripts/cleanup-committed-runtime-artifacts.sh # 实际 git rm --cached
#
# 运行后建议：
#   git status           # 确认待 commit 的删除
#   git commit -m "chore: remove tracked runtime artifacts (outbox/webhook)"
#
# 注意：这不会重写历史；已推送到远端的 PR/branch 不受影响。
# 若需彻底从历史移除（例如包含敏感 webhook 内容），额外跑 git-filter-repo。

set -euo pipefail

PATTERNS=(
  'MODstore_deploy/modstore_server/webhook_events/.*\.json$'
  'MODstore_deploy/modstore_server/data/event_outbox\.jsonl$'
  'MODstore_deploy/modstore_server/data/event_outbox_.*\.jsonl$'
  'MODstore_deploy/modstore_server/data/payment_orders/'
  'MODstore_deploy/modstore_server/data/chroma/'
)

cd "$(git rev-parse --show-toplevel)"

echo "[info] scanning git index for runtime artifacts..."
victims=()
for pat in "${PATTERNS[@]}"; do
  while IFS= read -r f; do
    [ -n "$f" ] && victims+=("$f")
  done < <(git ls-files | grep -E "$pat" || true)
done

if [ ${#victims[@]} -eq 0 ]; then
  echo "[ok] no tracked runtime artifacts; nothing to remove."
  exit 0
fi

echo "[info] found ${#victims[@]} tracked runtime artifact(s):"
for f in "${victims[@]}"; do
  echo "  - $f"
done

if [ "${APPLY:-0}" = "1" ]; then
  echo "[info] running: git rm --cached"
  git rm --cached --quiet "${victims[@]}"
  echo "[ok] removed from index; files still exist in working tree."
  echo "    run: git status; git commit -m \"chore: untrack runtime artifacts\""
else
  echo ""
  echo "[dry-run] 设置 APPLY=1 后会执行 git rm --cached 把上述文件从索引移除。"
fi
