#!/usr/bin/env bash
# 同步 GENERIC 9 bridge → FHD/mods-admin-runtime/（管理端专用，与企业空 mods/ 分离）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
EXPORT="${XCMAX_ROOT}/mods-export-2026-06-07"
DEST="${FHD_ROOT}/mods-admin-runtime"
DRY_RUN=0

GENERIC_BRIDGE_MODS=(
  xcagi-planner-bridge
  xcagi-erp-domain-bridge
  xcagi-workflow-visualization-bridge
  xcagi-approval-bridge
  xcagi-lan-license-bridge
  xcagi-model-payment-bridge
  xcagi-neuro-bus-bridge
  xcagi-office-employee-pack-bridge
  xcagi-customer-service-bridge
)

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: bash scripts/dev/sync-admin-mod-runtime.sh [--dry-run]"
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$EXPORT" ]]; then
  echo "Missing export archive: $EXPORT" >&2
  echo "Run migrate-mods-2026-06-07.sh first." >&2
  exit 1
fi

mkdir -p "$DEST"

echo "Source: $EXPORT"
echo "Dest:   $DEST"
echo "Mods:   ${#GENERIC_BRIDGE_MODS[@]}"
echo

for mod in "${GENERIC_BRIDGE_MODS[@]}"; do
  src="${EXPORT}/${mod}"
  if [[ ! -d "$src" ]]; then
    echo "[skip] missing in export: $mod" >&2
    continue
  fi
  echo "  sync  $mod"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    continue
  fi
  rm -rf "${DEST}/${mod}"
  cp -R "$src" "${DEST}/${mod}"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "[dry-run] No files changed."
  exit 0
fi

cat >"${DEST}/README.md" <<'EOF'
# 管理端 Mod 运行目录（mods-admin-runtime）

与企业端空目录 `FHD/mods/` 分离。预置 GENERIC 9 bridge，供 `:5011` 管理端与后端扫描。

同步：

  bash FHD/scripts/dev/sync-admin-mod-runtime.sh

源：`../mods-export-2026-06-07/`（勿手改 export，改 Mod 后重新 sync）
EOF

echo
echo "Done. Admin runtime: $DEST"
