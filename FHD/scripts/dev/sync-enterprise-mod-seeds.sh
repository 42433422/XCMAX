#!/usr/bin/env bash
# 企业开发：将宿主 bridge / 工作流 / 表格工具等种子补入 FHD/mods/（方案 B：仓库种子，非仅市场下载）
# 源优先级：XCAGI/data/desktop-dev/mods → mods-admin-runtime → XCAGI/mods
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEST="${FHD_ROOT}/mods"
DESKTOP_DEV="${FHD_ROOT}/XCAGI/data/desktop-dev/mods"
ADMIN_RUNTIME="${FHD_ROOT}/mods-admin-runtime"
XCAGI_MODS="${FHD_ROOT}/XCAGI/mods"
HOST_FOUNDATION_DIR="${DEST}/_employees/xcagi-host-foundation-employee"
FORCE=0
DRY_RUN=0

ENTERPRISE_SEED_MODS=(
  xcagi-planner-bridge
  xcagi-erp-domain-bridge
  xcagi-workflow-visualization-bridge
  xcagi-approval-bridge
  xcagi-lan-license-bridge
  xcagi-model-payment-bridge
  xcagi-neuro-bus-bridge
  xcagi-office-employee-pack-bridge
  xcagi-customer-service-bridge
  xcagi-core-workflow-employees
  xcagi-planner-excel-tools
  wechat-contacts-ai-employee
  lan-gate-ai-employee
)

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: bash FHD/scripts/dev/sync-enterprise-mod-seeds.sh [--force] [--dry-run]

  补全 FHD/mods/ 企业引导所需种子（bridge、core-workflow、planner-excel、触点员工包）。
  完成后建议：python FHD/scripts/dev/mods_ssot.py sync

Options:
  --force    已存在目录时覆盖复制
  --dry-run  仅打印计划，不写盘
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

resolve_src() {
  local mod="$1"
  local d
  for d in "$DESKTOP_DEV" "$ADMIN_RUNTIME" "$XCAGI_MODS"; do
    if [[ -d "${d}/${mod}" && -f "${d}/${mod}/manifest.json" ]]; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

ensure_host_foundation_seed() {
  if [[ -f "${HOST_FOUNDATION_DIR}/manifest.json" ]]; then
    echo "[ok]   host foundation employee seed present"
    return 0
  fi
  echo "[seed] xcagi-host-foundation-employee (minimal manifest)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  mkdir -p "$HOST_FOUNDATION_DIR"
  cat >"${HOST_FOUNDATION_DIR}/manifest.json" <<'EOF'
{
  "id": "xcagi-host-foundation-employee",
  "name": "宿主基础能力（预装员工）",
  "version": "10.0.0",
  "author": "成都修茈科技有限公司",
  "description": "以员工包交付的通用宿主底座：安装后自动写入对话/ERP/审批/客服等 bridge Mod。",
  "artifact": "employee_pack",
  "scope": "global",
  "dependencies": { "xcagi": ">=10.0.0" },
  "employee": { "id": "host_foundation", "label": "宿主基础能力" },
  "config": { "host_foundation_pack": true, "edition": "generic" }
}
EOF
}

echo "Dest:        $DEST"
echo "desktop-dev: $DESKTOP_DEV"
echo "admin-rt:    $ADMIN_RUNTIME"
echo "xcagi/mods:  $XCAGI_MODS"
echo "Mods:        ${#ENTERPRISE_SEED_MODS[@]}"
echo

ensure_host_foundation_seed

missing=0
for mod in "${ENTERPRISE_SEED_MODS[@]}"; do
  if [[ -d "${DEST}/${mod}" && -f "${DEST}/${mod}/manifest.json" && "$FORCE" -eq 0 ]]; then
    echo "[skip] $mod (already in mods/)"
    continue
  fi
  src_root=""
  if src_root="$(resolve_src "$mod")"; then
    :
  else
    echo "[miss] $mod — not found in any seed root" >&2
    missing=$((missing + 1))
    continue
  fi
  src="${src_root}/${mod}"
  echo "[sync] $mod  ← ${src_root}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    continue
  fi
  rm -rf "${DEST}/${mod}"
  cp -R "$src" "${DEST}/${mod}"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "[dry-run] No mod directories changed."
  exit 0
fi

echo
if [[ "$missing" -gt 0 ]]; then
  echo "Warning: $missing mod(s) missing from all seed roots." >&2
fi
echo "Done. Enterprise mod seeds → $DEST"
echo "Next: python ${SCRIPT_DIR}/mods_ssot.py sync"
