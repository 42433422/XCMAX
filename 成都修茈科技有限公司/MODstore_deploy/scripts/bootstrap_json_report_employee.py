"""Bootstrap json-report-employee 到 library（json_quant_report runtime）。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BRIEF = """员工包 ID：json-report-employee
员工名称：JSON 量化报告员
版本：1.0.0

读取 document_full.json（Word 全量读取同 schema）或 execute_result 包装 JSON，
在 direct_python 内调用 LLM 生成美观的 HTML 量化报告 outputs/quantitative_report.html。
handlers 必须为 direct_python；禁止编造 JSON 中不存在的数据。"""


def _empty_asset_manifest() -> dict:
    return {
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }


def main() -> int:
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        build_rule_spec,
        materialize_asset_employee_pack,
    )
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path
    from modstore_server.word_generate_runtime import minimal_document_full_json

    asset_manifest = _empty_asset_manifest()
    session_assets = Path(tempfile.mkdtemp(prefix="json_report_assets_"))
    inputs_dir = session_assets / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    sample = inputs_dir / "document_full.json"
    sample.write_text(
        json.dumps(minimal_document_full_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    asset_manifest["assets"].append(
        {
            "id": "document_full.json",
            "filename": "document_full.json",
            "kind": "example_input",
            "suffix": ".json",
            "storage_path": str(sample),
        }
    )

    rule_spec = build_rule_spec(BRIEF, asset_manifest)
    rule_spec["pack_id"] = "json-report-employee"
    manifest = _fallback_manifest(BRIEF, rule_spec)
    manifest["id"] = "json-report-employee"
    manifest["version"] = "1.0.0"
    manifest["name"] = "JSON 量化报告员"
    manifest["description"] = (
        "上传 document_full.json（或 execute_result 包装），"
        "由 LLM 生成美观 HTML 量化报告 quantitative_report.html。"
    )
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
    print(
        json.dumps(
            {
                "ok": True,
                "pack_id": dest.name,
                "path": str(dest),
                "runtime_kind": rule_spec.get("runtime_kind"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
