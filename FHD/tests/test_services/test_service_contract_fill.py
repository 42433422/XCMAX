"""测试 service_contract_fill 模块 - 服务合同字段填充。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

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
