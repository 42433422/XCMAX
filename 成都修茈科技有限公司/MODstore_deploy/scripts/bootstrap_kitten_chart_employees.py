"""Bootstrap 小猫分析可视化 chart-*-employee 到 MODstore library。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_DATASET = {
    "columns": ["月份", "销量", "渠道"],
    "rows": [
        {"月份": "1月", "销量": 120, "渠道": "线上"},
        {"月份": "2月", "销量": 98, "渠道": "线上"},
        {"月份": "3月", "销量": 156, "渠道": "线下"},
        {"月份": "4月", "销量": 142, "渠道": "线下"},
    ],
}

CHART_EMPLOYEES = [
    {
        "pkg_id": "chart-bar-employee",
        "name": "柱状图可视化员",
        "description": "上传 kitten 数据集 JSON/CSV，生成分类对比柱状图（chart_spec.json + chart.html）。",
        "industry": "数据/可视化",
        "brief_extra": "chart-bar-employee 柱状图可视化员",
    },
    {
        "pkg_id": "chart-line-employee",
        "name": "趋势折线可视化员",
        "description": "上传 kitten 数据集，生成时间序列折线图与趋势分析 HTML。",
        "industry": "数据/可视化",
        "brief_extra": "chart-line-employee 趋势折线可视化员",
    },
    {
        "pkg_id": "chart-pie-employee",
        "name": "占比饼图可视化员",
        "description": "上传 kitten 数据集，生成结构占比饼图与分布 HTML。",
        "industry": "数据/可视化",
        "brief_extra": "chart-pie-employee 占比饼图可视化员",
    },
    {
        "pkg_id": "chart-dashboard-employee",
        "name": "综合看板可视化员",
        "description": "上传 kitten 数据集，生成 KPI + 柱状 + 折线 + 饼图联动看板 HTML。",
        "industry": "数据/可视化",
        "brief_extra": "chart-dashboard-employee 综合看板可视化员",
    },
]


def _empty_asset_manifest() -> dict:
    return {
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }


def _bootstrap_one(meta: dict) -> dict:
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        materialize_asset_employee_pack,
    )
    from modstore_server.kitten_chart_runtime import build_kitten_chart_rule_spec
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path

    pkg_id = meta["pkg_id"]
    brief = f"""员工包 ID：{pkg_id}
员工名称：{meta['name']}
版本：1.0.0

{meta['brief_extra']}
读取 kitten 数据集（columns/rows JSON），在 direct_python 内生成 ECharts chart_spec.json 与 chart.html。
handlers 必须为 direct_python；禁止编造数据中不存在的行列。"""

    asset_manifest = _empty_asset_manifest()
    session_assets = Path(tempfile.mkdtemp(prefix=f"{pkg_id}_assets_"))
    inputs_dir = session_assets / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    sample = inputs_dir / "kitten_dataset.json"
    sample.write_text(json.dumps(SAMPLE_DATASET, ensure_ascii=False, indent=2), encoding="utf-8")
    asset_manifest["assets"].append(
        {
            "id": "kitten_dataset.json",
            "filename": "kitten_dataset.json",
            "kind": "example_input",
            "suffix": ".json",
            "storage_path": str(sample),
        }
    )

    rule_spec = build_kitten_chart_rule_spec(brief)
    rule_spec["pack_id"] = pkg_id
    manifest = _fallback_manifest(brief, rule_spec)
    manifest["id"] = pkg_id
    manifest["version"] = "1.0.0"
    manifest["name"] = meta["name"]
    manifest["description"] = meta["description"]
    manifest["artifact"] = "employee_pack"

    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        generated_convert_py=None,
    )
    lib = modstore_library_path()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = Path(tmp.name)
    try:
        dest = import_zip(tmp_path, lib, replace=True)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "pack_id": dest.name,
        "path": str(dest),
        "runtime_kind": rule_spec.get("runtime_kind"),
    }


def main() -> int:
    results = []
    for meta in CHART_EMPLOYEES:
        results.append(_bootstrap_one(meta))
    print(json.dumps({"ok": True, "bootstrapped": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
