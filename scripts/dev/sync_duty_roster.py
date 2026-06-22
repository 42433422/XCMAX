#!/usr/bin/env python3
"""从 SSOT 生成编制派生文件，消除 7 处硬编码手动同步。

SSOT（单一真相源）:
  - FHD/config/duty_roster.json        编制结构（areas + departments）
  - FHD/mods/_employees/*/manifest.json 员工元数据（name / description / area）

派生文件（由本脚本生成，禁止人手修改）:
  1. FHD/MODstore/modstore_server/duty_roster.py        (marker 区块)
  2. FHD/frontend/src/domain/yuangonDutyRoster.ts       (整体生成)
  3. FHD/app/infrastructure/mods/catalog_visibility.py  (改为运行时派生)
  4. FHD/mobile-harmony/entry/src/main/ets/models/MobileModels.ets (marker 区块)

用法:
  python scripts/dev/sync_duty_roster.py --generate   # 生成所有派生文件
  python scripts/dev/sync_duty_roster.py --check      # CI 校验（不一致则 exit 1）
  python scripts/dev/sync_duty_roster.py --generate --target frontend  # 只生成指定目标

CI SSOT 标识: 派生文件含 "CI SSOT: generated from" 头，人手修改会被 --check 拦截。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ── 路径常量 ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
FHD = ROOT / "FHD"
SSOT_JSON = FHD / "config" / "duty_roster.json"
MANIFESTS_DIR = FHD / "mods" / "_employees"

TARGETS = {
    "modstore": FHD / "MODstore" / "modstore_server" / "duty_roster.py",
    "frontend": FHD / "frontend" / "src" / "domain" / "yuangonDutyRoster.ts",
    "catalog": FHD / "app" / "infrastructure" / "mods" / "catalog_visibility.py",
    "mobile": FHD / "mobile-harmony" / "entry" / "src" / "main" / "ets" / "models" / "MobileModels.ets",
}

# CI SSOT 标识
SSOT_HEADER_PY = "# CI SSOT: generated from FHD/config/duty_roster.json + mods/_employees/*/manifest.json — DO NOT EDIT BY HAND"
SSOT_HEADER_TS = "// CI SSOT: generated from FHD/config/duty_roster.json + mods/_employees/*/manifest.json — DO NOT EDIT BY HAND"

# marker 区块标记
MARKER_BEGIN = "# CI SSOT BEGIN"
MARKER_END = "# CI SSOT END"
MARKER_BEGIN_TS = "// CI SSOT BEGIN"
MARKER_END_TS = "// CI SSOT END"

# 前端 UI 常量（非编制数据，作为模板常量保留）
DEPARTMENT_COLORS = {
    "ops_acquisition": "#22d3ee",
    "ops_partner": "#4ade80",
    "prod_web": "#fb923c",
    "prod_mod": "#a78bfa",
    "prod_software": "#facc15",
    "shared_retention": "#79c0ff",
}
CRAFT_SUBZONE_ID = "craft-pipeline"


# ── SSOT 读取 ────────────────────────────────────────────────────────────
def load_duty_roster() -> dict[str, Any]:
    """读取编制结构 SSOT。"""
    with open(SSOT_JSON, encoding="utf-8") as f:
        return json.load(f)


def scan_employee_manifests() -> dict[str, dict[str, str]]:
    """扫描员工包 manifest，返回 {id: {name, description, area}}。"""
    result: dict[str, dict[str, str]] = {}
    if not MANIFESTS_DIR.is_dir():
        return result
    for child in sorted(MANIFESTS_DIR.iterdir()):
        mp = child / "manifest.json"
        if not mp.is_file():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        mid = str(m.get("id") or child.name).strip()
        if not mid:
            continue
        ev2 = m.get("employee_config_v2") or {}
        ident = ev2.get("identity") or {}
        result[mid] = {
            "name": str(m.get("name") or ident.get("name") or mid),
            "description": str(m.get("description") or ident.get("description") or ""),
            "area": str(ident.get("area") or ""),
        }
    return result


# ── 格式化工具 ───────────────────────────────────────────────────────────
def _py_quote(s: str) -> str:
    """Python 字符串引号（双引号，转义内部双引号和换行符）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def _ts_quote(s: str) -> str:
    """TS 字符串引号（单引号，转义内部单引号和换行符）。"""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r") + "'"


def _py_ids_list(ids: list[str], indent: int = 12) -> str:
    """生成 Python ids 列表（每行一个，双引号）。"""
    if not ids:
        return "[]"
    pad = " " * indent
    inner = ",\n".join(pad + _py_quote(x) for x in ids)
    return "[\n" + inner + ",\n" + " " * (indent - 4) + "]"


def _ts_ids_list(ids: list[str], indent: int = 8) -> str:
    """生成 TS ids 数组（每行一个，单引号）。"""
    if not ids:
        return "[]"
    pad = " " * indent
    inner = ",\n".join(pad + _ts_quote(x) for x in ids)
    return "[\n" + inner + ",\n" + " " * (indent - 2) + "]"


# ── 生成 MODstore duty_roster.py（marker 区块）────────────────────────────
def gen_modstore_areas_block(doc: dict[str, Any]) -> str:
    """生成 YUANGON_AREAS 的 Python dict 文本。"""
    areas = doc.get("areas") or {}
    lines = [
        MARKER_BEGIN,
        "# 与 FHD config/duty_roster.json areas 块、market yuangonDutyRoster.ts 保持一致",
        "YUANGON_AREAS: Dict[str, Dict[str, object]] = {",
    ]
    for area_key, block in areas.items():
        label = block.get("label") or area_key
        ids = block.get("ids") or []
        lines.append(f'    {_py_quote(area_key)}: {{')
        lines.append(f'        "label": {_py_quote(label)},')
        lines.append(f'        "ids": {_py_ids_list(ids, indent=12)},')
        lines.append("    },")
    lines.append("}")
    lines.append(MARKER_END)
    return "\n".join(lines)


def gen_modstore_departments_block(doc: dict[str, Any]) -> str:
    """生成 SIX_LINE_DEPARTMENTS 的 Python dict 文本。"""
    depts = doc.get("departments") or {}
    lines = [
        MARKER_BEGIN,
        "# 六线部门（与 FHD config/duty_roster.json departments 块一致）",
        "SIX_LINE_DEPARTMENTS: Dict[str, Dict[str, object]] = {",
    ]
    for dept_key, dept in depts.items():
        label = dept.get("label") or dept_key
        five_line = dept.get("five_line_id") or dept_key
        subzones = dept.get("subzones") or {}
        lines.append(f'    {_py_quote(dept_key)}: {{')
        lines.append(f'        "label": {_py_quote(label)},')
        lines.append(f'        "five_line_id": {_py_quote(five_line)},')
        lines.append('        "subzones": {')
        for sz_key, sz in subzones.items():
            sz_label = sz.get("label") or sz_key
            sz_ids = sz.get("ids") or []
            lines.append(f'            {_py_quote(sz_key)}: {{"label": {_py_quote(sz_label)}, "ids": {_py_ids_list(sz_ids, indent=16)}}},')
        lines.append("        },")
        lines.append("    },")
    lines.append("}")
    lines.append(MARKER_END)
    return "\n".join(lines)


def generate_modstore_duty_roster(doc: dict[str, Any]) -> str:
    """生成 MODstore duty_roster.py 的完整内容。"""
    areas_block = gen_modstore_areas_block(doc)
    depts_block = gen_modstore_departments_block(doc)
    return f"""{SSOT_HEADER_PY}
\"\"\"与前端 AdminDutyEmployeeGraph 编制矩阵对齐的岗位 ID（单一后端来源）。\"\"\"

from __future__ import annotations

from typing import Dict, List, Optional

{areas_block}

{depts_block}


def all_planned_employee_ids() -> frozenset[str]:
    ids: List[str] = []
    for block in YUANGON_AREAS.values():
        ids.extend(block["ids"])  # type: ignore[arg-type]
    return frozenset(ids)


def yuangon_area_for_pkg(pkg_id: str) -> Optional[str]:
    \"\"\"编制矩阵中 ``pkg_id`` 所属区域目录名（``yuangon/<area>/…`` 第一段），未知返回 ``None``。\"\"\"
    pid = str(pkg_id or "").strip()
    if not pid:
        return None
    for area_key, block in YUANGON_AREAS.items():
        ids = block.get("ids") if isinstance(block.get("ids"), list) else []
        if pid in ids:
            return str(area_key)
    return None


def is_planned_duty_employee_pack(pkg_id: Optional[str], artifact: Optional[str]) -> bool:
    \"\"\"编制矩阵内的 ``employee_pack``：运维/管理侧在岗岗位，不参与公开市场展示。\"\"\"
    if str(artifact or "").strip() != "employee_pack":
        return False
    pid = str(pkg_id or "").strip()
    return bool(pid) and pid in all_planned_employee_ids()


def is_planned_duty_employee_id(pkg_id: Optional[str]) -> bool:
    \"\"\"编制矩阵内的任意岗位 ID（含非 employee_pack 的内部岗）。\"\"\"
    pid = str(pkg_id or "").strip()
    return bool(pid) and pid in all_planned_employee_ids()


def is_store_employee_pack(pkg_id: Optional[str], artifact: Optional[str]) -> bool:
    \"\"\"商店员工包（非编制内）：公开市场可上架的 employee_pack。\"\"\"
    if str(artifact or "").strip() != "employee_pack":
        return False
    return not is_planned_duty_employee_pack(pkg_id, artifact)


def normalize_employee_pack_id(pkg_id: Optional[str]) -> str:
    \"\"\"规范化员工包 ID（strip + lower），空值返回空串。\"\"\"
    return str(pkg_id or "").strip().lower()


def employee_partition_meta() -> Dict[str, object]:
    \"\"\"员工分区元数据（供 employee_runtime / market_shared 使用）。\"\"\"
    return {{
        "planned_ids": all_planned_employee_ids(),
        "areas": dict(YUANGON_AREAS),
        "departments": dict(SIX_LINE_DEPARTMENTS),
    }}
"""


# ── 生成前端 yuangonDutyRoster.ts（整体生成）──────────────────────────────
def gen_ts_areas(doc: dict[str, Any]) -> str:
    """生成 YUANGON_AREAS 的 TS 文本。"""
    areas = doc.get("areas") or {}
    lines = ["/**", " * 编制区域（与 FHD config/duty_roster.json areas 块一致）。", " */", "export const YUANGON_AREAS: Record<string, { label: string; ids: string[] }> = {"]
    for area_key, block in areas.items():
        label = block.get("label") or area_key
        ids = block.get("ids") or []
        lines.append(f"  {_ts_quote(area_key)}: {{")
        lines.append(f"    label: {_ts_quote(label)},")
        lines.append(f"    ids: {_ts_ids_list(ids, indent=6)},")
        lines.append("  },")
    lines.append("}")
    return "\n".join(lines)


def gen_ts_role_labels(manifests: dict[str, dict[str, str]], planned_ids: set[str]) -> str:
    """生成 YUANGON_PKG_ROLE_LABELS（只含编制内员工）。"""
    lines = ["/**", " * 编制员工中文名（来源于 mods/_employees 下各 manifest.json 的 name 字段）。", " */", "export const YUANGON_PKG_ROLE_LABELS: Record<string, string> = {"]
    for mid in sorted(planned_ids):
        name = manifests.get(mid, {}).get("name") or mid
        lines.append(f"  {_ts_quote(mid)}: {_ts_quote(name)},")
    lines.append("}")
    return "\n".join(lines)


def gen_ts_descriptions(manifests: dict[str, dict[str, str]], planned_ids: set[str]) -> str:
    """生成 YUANGON_PKG_DESCRIPTIONS（只含编制内员工）。"""
    lines = ["/**", " * 编制员工说明（来源于 mods/_employees 下各 manifest.json 的 description 字段）。", " */", "export const YUANGON_PKG_DESCRIPTIONS: Record<string, string> = {"]
    for mid in sorted(planned_ids):
        desc = manifests.get(mid, {}).get("description") or ""
        lines.append(f"  {_ts_quote(mid)}: {_ts_quote(desc)},")
    lines.append("}")
    return "\n".join(lines)


def gen_ts_departments(doc: dict[str, Any]) -> str:
    """生成 SIX_LINE_DEPARTMENTS 的 TS 文本。"""
    depts = doc.get("departments") or {}
    lines = [
        "export type DutySubzone = { label: string; ids: string[] }",
        "export type DutyDepartment = {",
        "  label: string",
        "  five_line_id: string",
        "  reserved?: boolean",
        "  subzones: Record<string, DutySubzone>",
        "}",
        "",
        "export const SIX_LINE_DEPARTMENTS: Record<string, DutyDepartment> = {",
    ]
    for dept_key, dept in depts.items():
        label = dept.get("label") or dept_key
        five_line = dept.get("five_line_id") or dept_key
        subzones = dept.get("subzones") or {}
        lines.append(f"  {dept_key}: {{")
        lines.append(f"    label: {_ts_quote(label)},")
        lines.append(f"    five_line_id: {_ts_quote(five_line)},")
        lines.append("    subzones: {")
        for sz_key, sz in subzones.items():
            sz_label = sz.get("label") or sz_key
            sz_ids = sz.get("ids") or []
            lines.append(f"      {_ts_quote(sz_key)}: {{ label: {_ts_quote(sz_label)}, ids: {_ts_ids_list(sz_ids, indent=8)} }},")
        lines.append("    },")
        lines.append("  },")
    lines.append("}")
    return "\n".join(lines)


def gen_ts_department_order(doc: dict[str, Any]) -> str:
    """生成 DEPARTMENT_ORDER。"""
    depts = doc.get("departments") or {}
    keys = list(depts.keys())
    items = ",\n".join(f"  {_ts_quote(k)}" for k in keys)
    return f"export const DEPARTMENT_ORDER = [\n{items},\n] as const"


def gen_ts_department_colors() -> str:
    """生成 DEPARTMENT_COLORS（UI 常量，模板硬编码）。"""
    lines = ["export const DEPARTMENT_COLORS: Record<string, string> = {"]
    for k, v in DEPARTMENT_COLORS.items():
        lines.append(f"  {k}: {_ts_quote(v)},")
    lines.append("}")
    return "\n".join(lines)


def generate_frontend_yuangon_duty_roster_ts(doc: dict[str, Any], manifests: dict[str, dict[str, str]]) -> str:
    """生成前端 yuangonDutyRoster.ts 的完整内容。"""
    areas = doc.get("areas") or {}
    planned_ids = set()
    for block in areas.values():
        for x in block.get("ids") or []:
            planned_ids.add(x)

    areas_ts = gen_ts_areas(doc)
    role_ts = gen_ts_role_labels(manifests, planned_ids)
    desc_ts = gen_ts_descriptions(manifests, planned_ids)
    depts_ts = gen_ts_departments(doc)
    order_ts = gen_ts_department_order(doc)
    colors_ts = gen_ts_department_colors()

    return f"""{SSOT_HEADER_TS}
/**
 * 编制矩阵（CI SSOT 生成，禁止人手修改）。
 * 来源：FHD/config/duty_roster.json + mods/_employees 下各 manifest.json
 * 生成命令：python scripts/dev/sync_duty_roster.py --generate --target frontend
 */

{areas_ts}

/** 编制内全部员工包 ID（从 YUANGON_AREAS 聚合，用于工作台过滤与删除保护）。 */
export const ALL_PLANNED_YUANGON_PKG_IDS: ReadonlySet<string> = new Set(
  (Object.values(YUANGON_AREAS) as {{ ids: string[] }}[]).flatMap((b) => b.ids),
)

{role_ts}

{desc_ts}

{depts_ts}

{order_ts}

{colors_ts}

export const CRAFT_SUBZONE_ID = {_ts_quote(CRAFT_SUBZONE_ID)}
"""


# ── 生成 catalog_visibility.py（改为运行时派生）──────────────────────────
def generate_catalog_visibility_py() -> str:
    """生成 catalog_visibility.py（改为从 SSOT 运行时派生，不再硬编码 ID 集合）。"""
    return f"""{SSOT_HEADER_PY}
\"\"\"远端 Catalog 行是否应对 XCAGI 商店展示（与 AI 市场 /api/market/catalog 对齐）。\"\"\"

from __future__ import annotations

from typing import Any

from app.mod_sdk.duty_roster import all_planned_duty_employee_ids

# 编制内全部岗位 ID（运行时从 FHD/config/duty_roster.json 派生，不再硬编码）
_PLANNED_DUTY_EMPLOYEE_IDS: frozenset[str] = all_planned_duty_employee_ids()


def is_internal_duty_catalog_id(pkg_id: str) -> bool:
    pid = str(pkg_id or "").strip()
    return bool(pid) and pid in _PLANNED_DUTY_EMPLOYEE_IDS


def is_planned_duty_employee_pack(pkg_id: str, artifact: str | None) -> bool:
    if is_internal_duty_catalog_id(pkg_id):
        return True
    if str(artifact or "").strip().lower() != "employee_pack":
        return False
    return is_internal_duty_catalog_id(pkg_id)


def is_public_catalog_row(row: dict[str, Any]) -> bool:
    \"\"\"过滤：编制内岗、草稿、无下载地址、未上架 employee_pack。\"\"\"
    if not isinstance(row, dict):
        return False
    pid = str(row.get("id") or row.get("pkg_id") or "").strip()
    if not pid:
        return False
    ver = str(row.get("version") or "").strip()
    artifact = str(row.get("artifact") or "mod").strip().lower()

    if is_internal_duty_catalog_id(pid):
        return False

    if row.get("public_listing") is False:
        return False

    channel = str(row.get("release_channel") or "stable").strip().lower()
    if channel == "draft" or ver.startswith("draft-"):
        return False

    stored = bool(str(row.get("stored_filename") or "").strip())
    download_url = bool(str(row.get("download_url") or "").strip())
    if not stored and not download_url:
        return False

    if row.get("public_listing") is True:
        return True
    if artifact == "employee_pack":
        return False
    return True
"""


# ── 生成 MobileModels.ets（marker 区块）──────────────────────────────────
def gen_mobile_areas_block(doc: dict[str, Any]) -> str:
    """生成 MobileModels.ets 的 YUANGON_AREAS ArkTS 数组文本。"""
    areas = doc.get("areas") or {}
    lines = [MARKER_BEGIN_TS, "/**", " * 编制区域常量表（CI SSOT 生成，与前端 yuangonDutyRoster.ts YUANGON_AREAS 对齐）。", " * 后端 admin/home 返回的 duty 员工按 yuangon_area 归入这些区域。", " */", "export const YUANGON_AREAS: DutyAreaInfo[] = ["]
    for area_key, block in areas.items():
        label = block.get("label") or area_key
        ids = block.get("ids") or []
        ids_str = ", ".join(_ts_quote(x) for x in ids)
        lines.append("  {")
        lines.append(f"    id: {_ts_quote(area_key)},")
        lines.append(f"    label: {_ts_quote(label)},")
        lines.append(f"    ids: [{ids_str}]")
        lines.append("  },")
    lines.append("];")
    lines.append(MARKER_END_TS)
    return "\n".join(lines)


# ── marker 区块替换工具 ──────────────────────────────────────────────────
def replace_marker_block(content: str, begin_marker: str, end_marker: str, new_block: str) -> str:
    """替换文件中 marker 区块之间的内容。"""
    pattern = re.compile(
        re.escape(begin_marker) + r".*?" + re.escape(end_marker),
        re.DOTALL,
    )
    if not pattern.search(content):
        raise ValueError(f"未找到 marker 区块: {begin_marker} ... {end_marker}")
    return pattern.sub(new_block, content)


# ── 主逻辑 ───────────────────────────────────────────────────────────────
def generate_target(target: str, doc: dict[str, Any], manifests: dict[str, dict[str, str]]) -> str:
    """生成指定目标的文件内容。"""
    if target == "modstore":
        return generate_modstore_duty_roster(doc)
    if target == "frontend":
        return generate_frontend_yuangon_duty_roster_ts(doc, manifests)
    if target == "catalog":
        return generate_catalog_visibility_py()
    if target == "mobile":
        # mobile 用 marker 区块替换
        path = TARGETS["mobile"]
        content = path.read_text(encoding="utf-8")
        new_block = gen_mobile_areas_block(doc)
        return replace_marker_block(content, MARKER_BEGIN_TS, MARKER_END_TS, new_block)
    raise ValueError(f"未知目标: {target}")


def check_target(target: str, doc: dict[str, Any], manifests: dict[str, dict[str, str]]) -> bool:
    """校验目标文件是否与 SSOT 一致。"""
    path = TARGETS[target]
    if not path.is_file():
        print(f"  [FAIL] {target}: 文件不存在 {path}")
        return False
    expected = generate_target(target, doc, manifests)
    actual = path.read_text(encoding="utf-8")
    if expected.strip() == actual.strip():
        print(f"  [OK]   {target}")
        return True
    print(f"  [FAIL] {target}: 与 SSOT 不一致（需运行 --generate）")
    # 显示前 3 行差异
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            print(f"    L{i+1} 期望: {e[:100]}")
            print(f"    L{i+1} 实际: {a[:100]}")
            break
    if len(exp_lines) != len(act_lines):
        print(f"    行数差异: 期望 {len(exp_lines)} 实际 {len(act_lines)}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="从 SSOT 生成编制派生文件")
    parser.add_argument("--generate", action="store_true", help="生成派生文件")
    parser.add_argument("--check", action="store_true", help="CI 校验（不一致则 exit 1）")
    parser.add_argument("--target", choices=list(TARGETS.keys()), help="只处理指定目标")
    args = parser.parse_args()

    if not args.generate and not args.check:
        parser.print_help()
        return 1

    doc = load_duty_roster()
    manifests = scan_employee_manifests()
    targets = [args.target] if args.target else list(TARGETS.keys())

    if args.check:
        print("CI SSOT 校验:")
        all_ok = True
        for t in targets:
            if not check_target(t, doc, manifests):
                all_ok = False
        if all_ok:
            print("全部一致 ✓")
            return 0
        print("存在漂移！请运行: python scripts/dev/sync_duty_roster.py --generate")
        return 1

    if args.generate:
        for t in targets:
            content = generate_target(t, doc, manifests)
            path = TARGETS[t]
            path.write_text(content, encoding="utf-8")
            print(f"  [生成] {t}: {path.relative_to(ROOT)}")
        print("生成完成。请提交变更。")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
