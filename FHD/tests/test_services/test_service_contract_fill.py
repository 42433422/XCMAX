"""测试 service_contract_fill 模块 - 服务合同字段填充。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import service_contract_fill as contracts
from app.services import user_cs_pipeline as pipelines
from app.services.kitten_ai_document import generate as document_renderer
from app.services.service_contract_fill import (
    FIELD_SCHEMA,
    build_contract_wechat_hint,
    build_merged_fields,
    contract_assets_dir,
    generated_contracts_dir,
    list_field_schema,
    load_field_overrides,
    save_field_overrides,
)


@pytest.fixture(autouse=True)
def _tmp_roots(tmp_path, monkeypatch):
    """将存储目录重定向到临时目录。"""
    from app.services import service_contract_fill as mod

    def _mock_roots():
        return [tmp_path]

    monkeypatch.setattr(mod, "_pipeline_roots", _mock_roots)
    return tmp_path


class TestListFieldSchema:
    """测试 list_field_schema 函数。"""

    def test_returns_list(self):
        schema = list_field_schema()
        assert isinstance(schema, list)
        assert len(schema) > 0

    def test_schema_has_required_keys(self):
        schema = list_field_schema()
        for field in schema:
            assert "key" in field
            assert "label" in field
            assert "type" in field

    def test_schema_contains_known_fields(self):
        schema = list_field_schema()
        keys = [f["key"] for f in schema]
        assert "party_a_name" in keys
        assert "total_amount_number" in keys
        assert "sign_date" in keys

    def test_returns_copy(self):
        s1 = list_field_schema()
        s2 = list_field_schema()
        assert s1 is not s2


class TestLoadFieldOverrides:
    """测试 load_field_overrides 函数。"""

    def test_no_file_returns_empty(self, _tmp_roots):
        result = load_field_overrides(99999)
        assert result == {}

    def test_save_and_load_roundtrip(self, _tmp_roots):
        values = {"party_a_name": "测试公司", "total_amount_number": "10000"}
        save_field_overrides(100, values)
        loaded = load_field_overrides(100)
        assert loaded["party_a_name"] == "测试公司"
        assert loaded["total_amount_number"] == "10000"

    def test_corrupted_file_returns_empty(self, _tmp_roots):
        path = _tmp_roots.parent / "user_cs_contract_fields" / "200.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json{{{", encoding="utf-8")
        result = load_field_overrides(200)
        assert result == {}

    def test_non_dict_returns_empty(self, _tmp_roots):
        path = _tmp_roots.parent / "user_cs_contract_fields" / "300.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["not", "dict"]), encoding="utf-8")
        result = load_field_overrides(300)
        assert result == {}


class TestSaveFieldOverrides:
    """测试 save_field_overrides 函数。"""

    def test_saves_values(self, _tmp_roots):
        values = {"party_a_name": "公司A"}
        result = save_field_overrides(100, values)
        assert result["party_a_name"] == "公司A"

    def test_filters_none_values(self, _tmp_roots):
        values = {"party_a_name": "公司A", "total_amount_number": None}
        result = save_field_overrides(100, values)
        assert "party_a_name" in result
        assert "total_amount_number" not in result

    def test_converts_values_to_string(self, _tmp_roots):
        values = {"total_amount_number": 10000}
        result = save_field_overrides(100, values)
        assert result["total_amount_number"] == "10000"


class TestBuildContractWechatHint:
    """测试 build_contract_wechat_hint 函数。"""

    def test_basic_hint(self):
        hint = build_contract_wechat_hint("张三公司", "contract_100.docx")
        assert "张三公司" in hint
        assert "contract_100.docx" in hint
        assert "服务合同草案已生成" in hint

    def test_empty_name_defaults(self):
        hint = build_contract_wechat_hint("", "")
        assert "客户" in hint
        assert "合同.docx" in hint

    def test_whitespace_name_defaults(self):
        hint = build_contract_wechat_hint("   ", "   ")
        assert "客户" in hint


class TestBuildMergedFields:
    """测试 build_merged_fields 函数。"""

    def test_merged_fields_has_all_schema_keys(self, _tmp_roots):
        mock_pipeline = {
            "erp_customer_name": "测试公司",
            "username": "张三",
            "contract_fields": {},
        }
        with patch("app.services.service_contract_fill.load_pipeline", return_value=mock_pipeline):
            result = build_merged_fields(100, username="张三")
            for field in FIELD_SCHEMA:
                assert field["key"] in result

    def test_overrides_take_precedence(self, _tmp_roots):
        # Use a unique user ID to avoid state leakage
        save_field_overrides(101, {"party_a_name": "覆盖公司"})
        mock_pipeline = {
            "erp_customer_name": "原公司",
            "contract_fields": {},
        }
        with patch("app.services.service_contract_fill.load_pipeline", return_value=mock_pipeline):
            result = build_merged_fields(101)
            assert result["party_a_name"] == "覆盖公司"

    def test_fallback_to_pipeline_stored(self, _tmp_roots):
        # Use a unique user ID with no overrides saved
        mock_pipeline = {
            "erp_customer_name": "管道公司",
            "contract_fields": {"party_a_name": "存储公司"},
        }
        with patch("app.services.service_contract_fill.load_pipeline", return_value=mock_pipeline):
            result = build_merged_fields(102)
            assert result["party_a_name"] == "存储公司"

    def test_fallback_to_erp_customer_name(self, _tmp_roots):
        # Use a unique user ID with no overrides and no stored fields
        mock_pipeline = {
            "erp_customer_name": "ERP公司",
            "contract_fields": {},
        }
        with patch("app.services.service_contract_fill.load_pipeline", return_value=mock_pipeline):
            result = build_merged_fields(103)
            assert result["party_a_name"] == "ERP公司"

    def test_sign_date_auto_filled(self, _tmp_roots):
        mock_pipeline = {"contract_fields": {}}
        with patch("app.services.service_contract_fill.load_pipeline", return_value=mock_pipeline):
            result = build_merged_fields(100)
            assert result["sign_date"] != ""


class TestGeneratedContractsDir:
    """测试 generated_contracts_dir 函数。"""

    def test_returns_path(self, _tmp_roots):
        path = generated_contracts_dir()
        assert "user_cs_contracts" in str(path)
        assert "generated" in str(path)


class TestContractAssetsDir:
    """测试 contract_assets_dir 函数。"""

    def test_returns_path(self, _tmp_roots):
        path = contract_assets_dir()
        assert "user_cs_contracts" in str(path)
        assert "assets" in str(path)


_CONTRACT_VALUES = {
    "party_a_name": "合成客户甲 <&>",
    "total_amount_number": "1280.50",
    "sign_date": "2026-10-22",
    "main_function_list": "需求梳理\n接口集成",
}
_CONTRACT_TEXT = (
    "服务合同草案\n甲方：合成客户甲 <&>\n金额：1280.50 元\n"
    "签署日期：2026-10-22\n功能清单：需求梳理\n接口集成\n"
)
_CONTRACT_FILENAME = "contract_8001_20261022_101112.docx"


@pytest.fixture
def _contract_generation(tmp_path, monkeypatch):
    root = tmp_path / "pipelines"
    root.mkdir()
    monkeypatch.setattr(contracts, "_pipeline_roots", lambda: [root])
    monkeypatch.setattr(pipelines, "_pipeline_roots", lambda: [root])

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 22, 10, 11, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(contracts, "datetime", FixedDateTime)

    def reject_llm(*args, **kwargs):
        raise AssertionError("Contract rendering must not invoke an LLM")

    monkeypatch.setattr(document_renderer, "draft_document_spec", reject_llm)
    monkeypatch.setattr(document_renderer, "get_openai_compatible_client", reject_llm)
    return contracts.generated_contracts_dir()


def _contract_text(content):
    with ZipFile(BytesIO(content)) as package:
        assert package.testzip() is None
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(
            package.namelist()
        )
    document = Document(BytesIO(content))
    return "\n".join(paragraph.text for paragraph in document.paragraphs) + "\n"


@pytest.fixture
def _contract_client(_contract_generation, monkeypatch):
    path = (
        Path(contracts.__file__).resolve().parents[2]
        / "mods/xcagi-customer-service-bridge/backend/blueprints.py"
    )
    spec = importlib.util.spec_from_file_location("synthetic_contract_artifact_bridge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    module.register_fastapi_routes(app, "synthetic-contract-artifacts")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_generated_contract_is_real_ooxml_and_preserves_public_metadata(
    _contract_generation, monkeypatch
):
    merged = Mock(side_effect=AssertionError("Explicit fields must not be replaced"))
    monkeypatch.setattr(contracts, "build_merged_fields", merged)
    result = contracts.generate_contract_docx(
        8001, username="Unused fallback", field_values=dict(_CONTRACT_VALUES)
    )
    path = _contract_generation / _CONTRACT_FILENAME

    assert result == {
        "filename": _CONTRACT_FILENAME,
        "party_a_name": _CONTRACT_VALUES["party_a_name"],
        "total_amount_number": "1280.50",
        "path": str(path),
    }
    merged.assert_not_called()
    assert _contract_text(path.read_bytes()) == _CONTRACT_TEXT


@pytest.mark.parametrize("field_values", [None, {}])
def test_generated_contract_keeps_merged_field_fallback(_contract_generation, field_values):
    doc = pipelines.load_pipeline(8001, username="Synthetic owner")
    doc["contract_fields"] = dict(_CONTRACT_VALUES, party_a_name="Original stored name")
    pipelines.save_pipeline(doc)
    contracts.save_field_overrides(8001, {"party_a_name": _CONTRACT_VALUES["party_a_name"]})

    result = contracts.generate_contract_docx(
        8001, username="Synthetic owner", field_values=field_values
    )

    assert result["party_a_name"] == _CONTRACT_VALUES["party_a_name"]
    assert result["total_amount_number"] == "1280.50"
    assert _contract_text(Path(result["path"]).read_bytes()) == _CONTRACT_TEXT


@pytest.mark.parametrize("username,party_a", [("合成用户名", "合成用户名"), ("", "客户8001")])
def test_generated_contract_keeps_party_name_fallback(_contract_generation, username, party_a):
    result = contracts.generate_contract_docx(
        8001, username=username, field_values={"total_amount_number": "12"}
    )

    assert result["party_a_name"] == party_a
    assert _contract_text(Path(result["path"]).read_bytes()) == (
        f"服务合同草案\n甲方：{party_a}\n金额：12 元\n签署日期：\n功能清单：\n"
    )


@pytest.mark.parametrize("failure", ["render", "publish"])
def test_generation_failure_preserves_existing_artifact_and_cleans_temporary_files(
    _contract_generation, monkeypatch, failure
):
    path = _contract_generation / _CONTRACT_FILENAME
    original = b"previous published artifact"
    path.write_bytes(original)
    if failure == "render":
        monkeypatch.setattr(
            document_renderer, "build_docx_bytes", Mock(side_effect=OSError("synthetic failure"))
        )
    else:
        original_replace = Path.replace

        def fail_publish(source, destination):
            if Path(destination) == path:
                assert _contract_text(source.read_bytes()) == _CONTRACT_TEXT
                raise OSError("synthetic failure")
            return original_replace(source, destination)

        monkeypatch.setattr(Path, "replace", fail_publish)

    with pytest.raises(OSError, match="synthetic failure"):
        contracts.generate_contract_docx(8001, field_values=dict(_CONTRACT_VALUES))

    assert path.read_bytes() == original
    assert list(_contract_generation.iterdir()) == [path]


def test_mod_route_generates_and_downloads_the_actual_word_artifact(
    _contract_generation, _contract_client
):
    doc = pipelines.load_pipeline(8001, username="Synthetic owner")
    doc["stage"] = "quoted"
    pipelines.save_pipeline(doc)
    response = _contract_client.post(
        "/api/mod/synthetic-contract-artifacts/user-cs/contract/generate",
        json={"market_user_id": 8001, "username": "Synthetic owner", "values": _CONTRACT_VALUES},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    result = response.json()["data"]
    assert result["filename"] == _CONTRACT_FILENAME
    downloaded = _contract_client.get(result["download_url"])
    assert downloaded.status_code == 200
    assert (
        downloaded.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert _CONTRACT_FILENAME in downloaded.headers["content-disposition"]
    assert downloaded.content == (_contract_generation / _CONTRACT_FILENAME).read_bytes()
    assert _contract_text(downloaded.content) == _CONTRACT_TEXT
    saved = pipelines.load_pipeline(8001)
    assert saved["stage"] == "contract_pending"
    assert saved["contract_filename"] == _CONTRACT_FILENAME
    assert len(saved["timeline"]) == 1
    assert saved["timeline"][0]["source"] == "contract_generate"


def test_mod_generation_publish_failure_does_not_report_success_or_advance_pipeline(
    _contract_generation, _contract_client, monkeypatch
):
    doc = pipelines.load_pipeline(8001, username="Synthetic owner")
    doc["stage"] = "quoted"
    pipelines.save_pipeline(doc)
    before = pipelines._pipeline_file(8001).read_bytes()
    target = _contract_generation / _CONTRACT_FILENAME
    original_replace = Path.replace

    def fail_publish(source, destination):
        if Path(destination) == target:
            raise OSError("synthetic publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_publish)
    response = _contract_client.post(
        "/api/mod/synthetic-contract-artifacts/user-cs/contract/generate",
        json={"market_user_id": 8001, "values": _CONTRACT_VALUES},
    )

    assert response.status_code == 500
    assert pipelines._pipeline_file(8001).read_bytes() == before
    assert list(_contract_generation.iterdir()) == []
