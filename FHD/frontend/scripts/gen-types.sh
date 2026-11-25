#!/usr/bin/env bash
# 从唯一后端 OpenAPI 契约生成 TypeScript 类型定义。
# npm run gen:types        更新生成文件
# npm run gen:types -- --check  检测生成文件缺失或漂移，不修改文件
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
CONTRACTS_FILE="$FRONTEND_DIR/../assets/contracts/openapi.json"
OUTPUT_FILE="$FRONTEND_DIR/src/types/api-generated.ts"
GENERATOR="$FRONTEND_DIR/node_modules/.bin/openapi-typescript"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then
  echo "用法: npm run gen:types [-- --check]" >&2
  exit 2
fi
if [[ ! -f "$CONTRACTS_FILE" ]]; then
  echo "::error::OpenAPI spec 不存在: $CONTRACTS_FILE" >&2
  echo "请先运行: cd .. && python scripts/dev/export_openapi.py" >&2
  exit 1
fi
if [[ ! -x "$GENERATOR" ]]; then
  echo "::error::缺少本地 openapi-typescript，请先运行 npm ci" >&2
  exit 1
fi

# 仅使用锁文件安装的生成器；失败时不覆盖上次生成的契约。
TEMP_DIR="$(mktemp -d "$(dirname "$OUTPUT_FILE")/.api-generated.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT
TEMP_FILE="$TEMP_DIR/api-generated.ts"
"$GENERATOR" "$CONTRACTS_FILE" -o "$TEMP_FILE"
if [[ ! -s "$TEMP_FILE" ]]; then
  echo "::error::生成的 API 类型为空" >&2
  exit 1
fi
if [[ ${1:-} == --check ]]; then
  if ! cmp -s "$OUTPUT_FILE" "$TEMP_FILE"; then
    echo "::error::生成的 API 类型缺失或与 OpenAPI 不一致，请运行 npm run gen:types" >&2
    exit 1
  fi
  echo "API 类型契约一致"
else
  mv -f "$TEMP_FILE" "$OUTPUT_FILE"
  echo "完成。请运行 npm run type-check 验证类型。"
fi
