#!/usr/bin/env bash
# 从中性行业包模板脚手架新建 *-industry Mod（Wave 2 SSOT）
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
MODS_ROOT="${FHD_ROOT}/mods"
TEMPLATE_MOD="${SCAFFOLD_TEMPLATE_MOD:-coating-industry}"

usage() {
  echo "用法: $0 <industry-baseline-id> <mod-id> [行业显示名]"
  echo "示例: $0 批发 wholesale-industry 批发分销行业"
  exit 1
}

[[ $# -ge 2 ]] || usage

INDUSTRY_ID="$1"
MOD_ID="$2"
INDUSTRY_NAME="${3:-${INDUSTRY_ID}行业}"
TARGET="${MODS_ROOT}/${MOD_ID}"

if [[ ! "$MOD_ID" =~ -industry$ ]]; then
  echo "错误: mod-id 须以 -industry 结尾（中性行业包约定）" >&2
  exit 1
fi

if [[ -d "$TARGET" ]]; then
  echo "错误: 已存在 ${TARGET}" >&2
  exit 1
fi

TEMPLATE="${MODS_ROOT}/${TEMPLATE_MOD}"
if [[ ! -f "${TEMPLATE}/manifest.json" ]]; then
  echo "错误: 模板不存在 ${TEMPLATE}/manifest.json" >&2
  exit 1
fi

echo "==> 复制模板 ${TEMPLATE_MOD} → ${MOD_ID}"
cp -R "$TEMPLATE" "$TARGET"

MANIFEST="${TARGET}/manifest.json"
python3 <<PY
import json
from pathlib import Path

path = Path("${MANIFEST}")
data = json.loads(path.read_text(encoding="utf-8"))
data["id"] = "${MOD_ID}"
data["name"] = "${INDUSTRY_NAME}包"
data["description"] = f"{data.get('description', '')}（{data['name']} · scaffold）".strip()
data["legacy_mod_ids"] = []
data["onboarding"] = {
    "custom_line_hint": f"{data['industry'].get('name', '${INDUSTRY_NAME}')}定制菜单与 AI 员工",
    "custom_mod_ids": [],
}
data["industry"]["id"] = "${INDUSTRY_ID}"
data["industry"]["name"] = "${INDUSTRY_NAME}"
data["frontend"]["pro_entry_path"] = "/${MOD_ID}"
data["import_templates"] = []
data["samples"] = []
data["migrations"] = {"schema_version": 1, "scripts_dir": "migrations"}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

mkdir -p "${TARGET}/data/import_templates" "${TARGET}/data/samples" "${TARGET}/migrations"
touch "${TARGET}/migrations/.gitkeep" "${TARGET}/data/import_templates/.gitkeep" "${TARGET}/data/samples/.gitkeep"

echo "==> 校验 manifest schema"
cd "$FHD_ROOT"
PYTHONPATH="$FHD_ROOT" python3 - <<PY
from pathlib import Path
from app.infrastructure.contracts.industry_package_validator import validate_industry_manifest

errs = validate_industry_manifest(Path("${MANIFEST}"))
if errs:
    raise SystemExit("schema errors: " + "; ".join(errs))
print("manifest OK")
PY

echo ""
echo "下一步:"
echo "  1. 编辑 ${MANIFEST} 的 industry.subsystems"
echo "  2. 在 config/industry_baseline.json 添加 industry_packages[\"${INDUSTRY_ID}\"].mod_id = \"${MOD_ID}\""
echo "  3. python scripts/dev/mods_ssot.py sync"
echo "完成: ${TARGET}"
