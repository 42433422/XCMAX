#!/usr/bin/env bash
# 将编制缺岗 yuangon 员工登记到本机 MODstore Catalog，并提示 FHD 市场基址。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../成都修茈科技有限公司" && pwd)"
MODSTORE="$REPO_ROOT/MODstore_deploy"
PKGS="${1:-fhd-core-maintainer,user-customer-service-officer,hex-quality-assessor}"
PY="${PY:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  PY=python3
fi

cd "$MODSTORE"
"$PY" modstore_server/scripts/onboard_yuangon_employees.py \
  --repo-root "$REPO_ROOT" \
  --pkg-ids "$PKGS" \
  --force

FILES_DIR="$MODSTORE/modstore_server/catalog_data/files"
MARKET_DIR="$MODSTORE/modstore_server/market_files"
mkdir -p "$MARKET_DIR"
IFS=',' read -r -a PKG_ARR <<< "$PKGS"
for id in "${PKG_ARR[@]}"; do
  id="${id// /}"
  [[ -z "$id" ]] && continue
  src="$FILES_DIR/${id}-1.0.0.xcemp"
  dst="$MARKET_DIR/${id}-1.0.0.xcemp"
  if [[ -f "$src" ]]; then
    cp -f "$src" "$dst"
  fi
done

echo ""
echo "本地 Catalog 已登记（modstore.db + catalog_data/files）。"
echo "请确保 FHD 后端连同一 MODstore，然后重启并刷新节点图："
echo "  export XCAGI_MARKET_BASE_URL=http://127.0.0.1:8765"
echo "  # 本机 MODstore 需已启动（默认 :8765）"
echo "  cd FHD/XCAGI && ./.venv 或 FHD/.venv 下: python run_fastapi.py --desktop --host 127.0.0.1 --port 5003"
