"""Regression: canvas save/export must not strip Word vendor runtime from library packs."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from modstore_server.employee_asset_pipeline import (
    build_employee_pack_zip_for_library,
    manifest_actions_handlers,
    materialize_asset_employee_pack,
    pack_has_direct_python_runtime,
    persist_manifest_to_pack_dir,
)
from modstore_server.word_extract_runtime import (
    build_word_extract_rule_spec,
    validate_word_extract_backend,
)
from modstore_server.workbench_api import _employee_handlers_contract_ok


def test_build_zip_for_library_includes_vendor(tmp_path: Path, monkeypatch):
    brief = "Word 文档全量提取，输出 JSON 和 txt"
    rule_spec = build_word_extract_rule_spec(brief)
    manifest = {
        "id": "word-full-extract-employee",
        "name": "Word 全量提取员",
        "version": "1.0.0",
        "employee_config_v2": {"actions": {"handlers": ["direct_python"]}},
    }
    pack_dir, _ = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={"assets": []},
        generated_convert_py=None,
    )
    lib = tmp_path / "library"
    lib.mkdir()
    target = lib / "word-full-extract-employee"
    import shutil

    shutil.copytree(pack_dir, target)
    monkeypatch.setattr(
        "modstore_server.employee_asset_pipeline.modstore_library_path",
        lambda: lib,
    )

    mf = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    mf["actions"] = {"handlers": ["direct_python"]}
    raw = build_employee_pack_zip_for_library("word-full-extract-employee", mf, pack_dir=target)
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        names = zf.namelist()
    assert any("backend/vendor" in n and "convert.py" in n for n in names)
    assert any(n.endswith("rule_spec.json") for n in names)


def test_build_zip_for_library_rejects_word_without_runtime(tmp_path: Path, monkeypatch):
    lib = tmp_path / "library"
    lib.mkdir()
    monkeypatch.setattr(
        "modstore_server.employee_asset_pipeline.modstore_library_path",
        lambda: lib,
    )
    mf = {
        "id": "word-full-extract-employee",
        "name": "Word 全量提取员",
        "description": "Word 文档全量提取所有格式与信息",
        "actions": {"handlers": ["direct_python"]},
        "perception": {"accepted_extensions": [".docx", ".doc"]},
    }
    with pytest.raises(ValueError, match="画布保存不能替代"):
        build_employee_pack_zip_for_library("word-full-extract-employee", mf)


def test_handlers_contract_fails_without_rule_spec_but_canvas_direct_python(tmp_path: Path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    mf = {
        "id": "word-full-extract-employee",
        "description": "Word 文档全量提取",
        "actions": {"handlers": ["direct_python"]},
        "perception": {"accepted_extensions": [".docx"]},
    }
    (pack_dir / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False), encoding="utf-8")
    ok, msg = _employee_handlers_contract_ok(pack_dir)
    assert not ok
    assert "generate" in msg or "vendor" in msg or "rule_spec" in msg


def test_handlers_contract_passes_with_materialized_pack():
    brief = "Word 全量提取 docx 输出 JSON"
    rule_spec = build_word_extract_rule_spec(brief)
    manifest = {
        "id": "word-full-extract-employee",
        "name": "Word 全量提取员",
        "version": "1.0.0",
        "employee_config_v2": {"actions": {"handlers": ["direct_python"]}},
    }
    pack_dir, _ = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={"assets": []},
        generated_convert_py=None,
    )
    assert pack_has_direct_python_runtime(pack_dir)
    ok, msg = _employee_handlers_contract_ok(pack_dir)
    assert ok, msg
    errs, _ = validate_word_extract_backend(pack_dir)
    assert not errs
    assert manifest_actions_handlers(
        json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    ) == ["direct_python"]


def test_persist_manifest_does_not_remove_vendor(tmp_path: Path):
    brief = "Word 全量提取"
    rule_spec = build_word_extract_rule_spec(brief)
    manifest = {
        "id": "word-full-extract-employee",
        "name": "Word 全量提取员",
        "version": "1.0.0",
        "employee_config_v2": {"actions": {"handlers": ["direct_python"]}},
    }
    pack_dir, _ = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={"assets": []},
        generated_convert_py=None,
    )
    vendor_before = list((pack_dir / "backend").rglob("convert.py"))
    assert vendor_before
    mf2 = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    mf2["description"] = "更新后的描述"
    persist_manifest_to_pack_dir(pack_dir, mf2, brief=brief)
    assert list((pack_dir / "backend").rglob("convert.py"))
