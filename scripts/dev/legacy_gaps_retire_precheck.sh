#!/usr/bin/env bash
# legacy_gaps_batch1/2 退役前检查：遥测 + 静态引用 + OpenAPI 快照提示。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "== Legacy usage (168h) =="
python3 scripts/dev/legacy_usage_report.py --since 168 || true

echo ""
echo "== Static references to legacy_gaps_batch =="
if command -v rg >/dev/null 2>&1; then
  rg -n "legacy_gaps_batch" app scripts tests .github 2>/dev/null || true
else
  grep -Rn "legacy_gaps_batch" app scripts tests .github 2>/dev/null || true
fi

echo ""
echo "== Edition policy (legacy gaps registration) =="
if command -v rg >/dev/null 2>&1; then
  rg -n "should_register_host_legacy_routes|legacy_gaps" app/mod_sdk/edition_policy.py app/fastapi_routes/__init__.py 2>/dev/null || true
else
  grep -En "should_register_host_legacy_routes|legacy_gaps" app/mod_sdk/edition_policy.py app/fastapi_routes/__init__.py 2>/dev/null || true
fi

echo ""
echo "退役准入：遥测 7 天=0 + 上表静态引用仅保留注册点 + OpenAPI diff 无意外 + full edition 冒烟。"
echo "快照写入：docs/reports/legacy_usage_snapshot.json（CI 可提交 --json 输出对比）"
