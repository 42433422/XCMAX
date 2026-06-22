#!/usr/bin/env bash
# 从后端 OpenAPI spec 生成 TypeScript 类型定义。
#
# 用法：
#   npm run gen:types
#
# 依赖：openapi-typescript（devDependency）
# 输入：../contracts/openapi.json（由 scripts/dev/export_openapi.py 生成）
# 输出：src/types/api-generated.ts
#
# 生成后可与 src/types/api.ts 中的手动扩展类型共存。
# 迁移策略：逐步将手动类型替换为生成类型，保留业务语义化别名。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
CONTRACTS_FILE="$FRONTEND_DIR/../contracts/openapi.json"
OUTPUT_FILE="$FRONTEND_DIR/src/types/api-generated.ts"

if [ ! -f "$CONTRACTS_FILE" ]; then
  echo "::error::OpenAPI spec 不存在: $CONTRACTS_FILE"
  echo "请先运行: cd .. && python scripts/dev/export_openapi.py"
  exit 1
fi

echo "生成 TypeScript 类型: $OUTPUT_FILE"
npx openapi-typescript "$CONTRACTS_FILE" -o "$OUTPUT_FILE"

echo "完成。请运行 npm run type-check 验证类型。"
