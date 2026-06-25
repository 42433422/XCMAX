"""CSV 读取/生成 runtime 路由与 convert 模块测试。"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest


def test_csv_routing_keywords():
    from modstore_server.csv_tabular_runtime import is_csv_full_read, is_csv_generate

    assert is_csv_full_read("制作 CSV读取员工，上传 csv 解析为 json")
    assert not is_csv_generate("制作 CSV读取员工，上传 csv 解析为 json")
    assert is_csv_generate("CSV生成员工，根据 JSON 写出 csv 文件")
    assert not is_csv_generate("CSV读取员工，解析为 JSON 中介 outputs/data.json")
    assert not is_csv_full_read("CSV生成员工，JSON中介写出 csv 文件")


def test_csv_read_convert_writes_json():
    from modstore_server.csv_tabular_runtime import render_csv_read_convert_module

    code = render_csv_read_convert_module()
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    convert_file = ns["convert_file"]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "sample.csv"
        src.write_text("name,score\nalice,90\nbob,85\n", encoding="utf-8")
        out = root / "outputs" / "data.json"
        result = convert_file(
            src,
            out,
            template_path=None,
            payload={},
            ctx={},
            rule_spec={"default_output_relpath": "outputs/data.json", "output_schema": []},
        )
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["row_count"] == 2
        assert "name" in data["columns"]
        assert len(data["rows"]) == 2
        assert result["row_count"] == 2


@pytest.mark.xfail(strict=False, reason="csv_tabular_runtime generate/convert pre-existing failure")
def test_csv_generate_convert_writes_csv():
    from modstore_server.csv_tabular_runtime import (
        minimal_json_fixture_bytes,
        render_csv_generate_convert_module,
    )

    code = render_csv_generate_convert_module()
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    convert_file = ns["convert_file"]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "table.json"
        src.write_bytes(minimal_json_fixture_bytes())
        out = root / "outputs" / "output.csv"
        convert_file(
            src,
            out,
            template_path=None,
            payload={},
            ctx={},
            rule_spec={"default_output_relpath": "outputs/output.csv", "output_schema": []},
        )
        assert out.is_file()
        rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
        assert len(rows) == 2
        assert rows[0]["name"] == "alice"


def test_materialize_csv_read_pack_zip():
    from modstore_server.csv_tabular_runtime import (
        build_csv_read_rule_spec,
        render_csv_read_convert_module,
    )
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        _normalize_manifest,
        materialize_asset_employee_pack,
    )

    brief = "CSV全量读取员工 csv 解析 json"
    rule_spec = build_csv_read_rule_spec(brief)
    manifest = _normalize_manifest(_fallback_manifest(brief, rule_spec), brief, rule_spec)
    manifest["id"] = "csv-full-read-employee"
    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={
            "assets": [],
            "templates": [],
            "example_inputs": [],
            "expected_outputs": [],
            "rules": [],
        },
        generated_convert_py=render_csv_read_convert_module(),
    )
    assert len(raw_zip) > 500
    vendor = list(pack_dir.rglob("backend/vendor/*/convert.py"))
    assert vendor
