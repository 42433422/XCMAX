#!/usr/bin/env bash
# 制作线 P1–P10：本地依赖安装 + 可选环境文件提示
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== 制作线本地安装 (FHD) =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: 需要 python3 >= 3.11" >&2
  exit 1
fi

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Python $PYVER"

echo ""
echo ">> 安装 MkDocs Material（文档站）"
python3 -m pip install --upgrade pip -q
python3 -m pip install -r requirements-docs.txt -q
python3 -m mkdocs --version

echo ""
echo ">> 校验 MkDocs 构建"
mkdocs build
echo "OK  site-docs/ 已生成"

MARKETING_ROOT="$(cd "$ROOT/../成都修茈科技有限公司" 2>/dev/null && pwd || true)"
if [[ -n "$MARKETING_ROOT" && -d "$MARKETING_ROOT/marketing-site" ]]; then
  echo ""
  echo ">> 营销站 Node 构建（可选）"
  if command -v npm >/dev/null 2>&1; then
  (
    cd "$MARKETING_ROOT/marketing-site"
    npm ci
    npm run build
    echo "OK  marketing-site build"
  )
  else
    echo "SKIP npm 未安装 — 跳过 marketing-site"
  fi
fi

echo ""
echo "== 环境配置 =="
ENV_EXAMPLE="$ROOT/config/operations_line.env.example"
if [[ -f "$ENV_EXAMPLE" ]]; then
  echo "请对照并写入："
  echo "  - FHD/.env"
  echo "  - 成都修茈科技有限公司/MODstore_deploy/.env.local"
  echo "模板: $ENV_EXAMPLE"
  echo "指南: docs/guides/PRODUCTION_LINE_SETUP.md"
fi

if [[ -x "$ROOT/scripts/verify_production_line_config.sh" ]]; then
  echo ""
  echo ">> 运行配置连通性检查（需已启动 FHD + MODstore）"
  "$ROOT/scripts/verify_production_line_config.sh" || true
fi

echo ""
echo "== 完成 =="
