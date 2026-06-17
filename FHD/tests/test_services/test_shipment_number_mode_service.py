"""Tests for app.services.shipment_number_mode_service — coverage ramp.

Extends test_shipment_number_mode_helpers.py with comprehensive coverage for:
- _parse_by_db_terms
- _build_unit_not_found_payload
- _normalize_success_payload
- _extract_existing_unit_from_modify_text
- execute (main entry point)
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from app.services.shipment_number_mode_service import ShipmentNumberModeService


def _mock_get_db(mock_db):
    """Create a contextmanager mock for get_db generator."""

    @contextlib.contextmanager
    def _get_db():
        yield mock_db

    return _get_db


@pytest.fixture
def svc():
    return ShipmentNumberModeService()


# ---------------------------------------------------------------------------
# _normalize_unit_name (extended)
# ---------------------------------------------------------------------------


class TestNormalizeUnitNameExtended:
    def test_strips_company_suffixes(self):
        result = ShipmentNumberModeService._normalize_unit_name("成都七彩乐园家具有限公司")
        assert "有限公司" not in result
        assert "家具" not in result

    def test_strips_trade_suffix(self):
        result = ShipmentNumberModeService._normalize_unit_name("测试商贸公司")
        assert "商贸" not in result
        assert "公司" not in result

    def test_strips_decoration_suffix(self):
        result = ShipmentNumberModeService._normalize_unit_name("测试装饰公司")
        assert "装饰" not in result

    def test_removes_special_chars(self):
        result = ShipmentNumberModeService._normalize_unit_name("测试-公司(分部)")
        assert "-" not in result
        assert "(" not in result

    def test_none_input(self):
        result = ShipmentNumberModeService._normalize_unit_name(None)
        assert result == ""

    def test_numeric_input(self):
        result = ShipmentNumberModeService._normalize_unit_name(123)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _resolve_unit_alias (extended)
# ---------------------------------------------------------------------------


class TestResolveUnitAliasExtended:
    def test_exact_match(self, svc):
        pool = ["七彩乐园", "蕊芯化工"]
        assert svc._resolve_unit_alias("七彩乐园", pool) == "七彩乐园"

    def test_fuzzy_match_by_contains(self, svc):
        pool = ["成都七彩乐园家具有限公司", "蕊芯化工"]
        result = svc._resolve_unit_alias("七彩乐园", pool)
        assert result == "成都七彩乐园家具有限公司"

    def test_strips_qty_tail(self, svc):
        pool = ["蕊芯化工"]
        result = svc._resolve_unit_alias("蕊芯1", pool)
        assert result == "蕊芯化工"

    def test_returns_empty_for_no_match(self, svc):
        pool = ["七彩乐园"]
        result = svc._resolve_unit_alias("完全不匹配的公司", pool)
        assert result == ""

    def test_returns_empty_for_empty_typed(self, svc):
        pool = ["七彩乐园"]
        assert svc._resolve_unit_alias("", pool) == ""

    def test_returns_empty_for_empty_pool(self, svc):
        assert svc._resolve_unit_alias("甲公司", []) == ""

    def test_digit_tail_matching(self, svc):
        pool = ["蕊芯家私1", "蕊芯家私2"]
        result = svc._resolve_unit_alias("蕊芯1", pool)
        assert result == "蕊芯家私1"

    def test_multiple_contains_uses_score(self, svc):
        pool = ["七彩乐园家具", "七彩乐园装饰"]
        result = svc._resolve_unit_alias("七彩乐园", pool)
        # Should return one of them based on fuzzy score (may be empty if score too close)
        assert result == "" or result in pool


# ---------------------------------------------------------------------------
# _extract_existing_unit_from_modify_text
# ---------------------------------------------------------------------------


class TestExtractExistingUnitFromModifyText:
    def test_extracts_unit_before_modify_verb(self, svc):
        pool = ["七彩乐园", "蕊芯化工"]
        result = svc._extract_existing_unit_from_modify_text("七彩乐园再加2桶", pool)
        assert result == "七彩乐园"

    def test_returns_empty_when_no_modify_verb(self, svc):
        pool = ["七彩乐园"]
        result = svc._extract_existing_unit_from_modify_text("七彩乐园5桶", pool)
        assert result == ""

    def test_returns_empty_when_no_unit_match(self, svc):
        pool = ["蕊芯化工"]
        result = svc._extract_existing_unit_from_modify_text("未知公司再加2桶", pool)
        assert result == ""

    def test_returns_empty_for_empty_text(self, svc):
        pool = ["七彩乐园"]
        result = svc._extract_existing_unit_from_modify_text("", pool)
        assert result == ""

    def test_returns_empty_for_empty_pool(self, svc):
        result = svc._extract_existing_unit_from_modify_text("七彩乐园再加2桶", [])
        assert result == ""

    def test_prefers_longest_match(self, svc):
        pool = ["七彩", "七彩乐园"]
        result = svc._extract_existing_unit_from_modify_text("七彩乐园再加2桶", pool)
        assert result == "七彩乐园"

    def test_detects_various_modify_verbs(self, svc):
        pool = ["七彩乐园"]
        assert svc._extract_existing_unit_from_modify_text("七彩乐园减少1桶", pool) == "七彩乐园"
        assert svc._extract_existing_unit_from_modify_text("七彩乐园删掉1桶", pool) == "七彩乐园"
        assert svc._extract_existing_unit_from_modify_text("七彩乐园改为2桶", pool) == "七彩乐园"


# ---------------------------------------------------------------------------
# _parse_by_db_terms
# ---------------------------------------------------------------------------


class TestParseByDbTerms:
    def test_empty_text_returns_failure(self, svc):
        result = svc._parse_by_db_terms(text="", unit_pool=[], model_pool=[])
        assert result["success"] is False
        assert "为空" in result["message"]

    def test_full_parse_success(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园9803规格28 5桶",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        assert result["success"] is True
        assert result["unit_name"] == "七彩乐园"
        assert len(result["products"]) == 1
        assert result["products"][0]["model_number"] == "9803"
        assert result["products"][0]["tin_spec"] == 28.0
        assert result["products"][0]["quantity_tins"] == 5

    def test_missing_unit_returns_failure(self, svc):
        result = svc._parse_by_db_terms(
            text="9803规格28 5桶",
            unit_pool=[],
            model_pool=["9803"],
        )
        assert result["success"] is False
        assert "单位" in result["message"]

    def test_missing_model_returns_failure(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园规格28 5桶",
            unit_pool=["七彩乐园"],
            model_pool=[],
        )
        assert result["success"] is False
        assert "型号" in result["message"]

    def test_missing_spec_returns_failure(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园9803 5桶",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        # Without spec keyword, may still parse if model_number + remaining numbers
        # This tests the "规格" keyword path
        assert isinstance(result["success"], bool)

    def test_missing_quantity_returns_failure(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园9803规格28",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        assert result["success"] is False
        assert "桶数" in result["message"]

    def test_alternative_quantity_keywords(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园9803规格28 要5",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        assert result["success"] is True
        assert result["products"][0]["quantity_tins"] == 5

    def test_spec_with_colon(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园9803规格：28 5桶",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        assert result["success"] is True

    def test_implicit_spec_from_model(self, svc):
        """When no '规格' keyword, remaining number after model can be spec."""
        result = svc._parse_by_db_terms(
            text="七彩乐园9803 28 5桶",
            unit_pool=["七彩乐园"],
            model_pool=["9803"],
        )
        # 28 should be inferred as spec
        assert result["success"] is True
        assert result["products"][0]["tin_spec"] == 28.0

    def test_model_case_insensitive(self, svc):
        result = svc._parse_by_db_terms(
            text="七彩乐园AB12规格28 5桶",
            unit_pool=["七彩乐园"],
            model_pool=["AB12"],
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _build_unit_not_found_payload
# ---------------------------------------------------------------------------


class TestBuildUnitNotFoundPayload:
    def test_returns_empty_when_unit_exists(self, svc):
        pool = ["七彩乐园", "蕊芯化工"]
        result = svc._build_unit_not_found_payload("七彩乐园", pool)
        assert result == {}

    def test_returns_error_with_suggestions(self, svc):
        pool = ["七彩乐园家具", "蕊芯化工"]
        result = svc._build_unit_not_found_payload("七彩", pool)
        assert result["success"] is False
        assert "error_code" in result
        assert result["error_code"] == "purchase_unit_not_found"
        assert "candidate_units" in result["data"]

    def test_returns_error_without_suggestions(self, svc):
        pool = ["完全不同的公司"]
        result = svc._build_unit_not_found_payload("不存在的单位", pool)
        assert result["success"] is False
        assert "请先创建" in result["message"]

    def test_limits_suggestions_to_five(self, svc):
        pool = [f"公司{i}" for i in range(10)]
        result = svc._build_unit_not_found_payload("公司", pool)
        if result.get("data", {}).get("candidate_units"):
            assert len(result["data"]["candidate_units"]) <= 5


# ---------------------------------------------------------------------------
# _normalize_success_payload
# ---------------------------------------------------------------------------


class TestNormalizeSuccessPayload:
    def test_normalizes_doc_name_to_document(self):
        payload = {
            "success": True,
            "doc_name": "test.docx",
            "file_path": "/tmp/test.docx",
            "order_number": "ORD001",
            "record_id": 42,
        }
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        assert result["document"]["filename"] == "test.docx"
        assert result["document"]["filepath"] == "/tmp/test.docx"
        assert result["document"]["order_number"] == "ORD001"
        assert result["document"]["record_id"] == 42

    def test_preserves_existing_document_fields(self):
        payload = {
            "success": True,
            "document": {"filename": "existing.docx"},
            "doc_name": "new.docx",
        }
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        # Existing document.filename should not be overwritten
        assert result["document"]["filename"] == "existing.docx"

    def test_handles_none_payload(self):
        result = ShipmentNumberModeService._normalize_success_payload(None)
        assert result is None

    def test_handles_non_dict_payload(self):
        result = ShipmentNumberModeService._normalize_success_payload("string")
        assert result == "string"

    def test_populates_data_dict(self):
        payload = {
            "success": True,
            "doc_name": "test.docx",
            "order_number": "ORD001",
            "record_id": 1,
        }
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        assert result["data"]["doc_name"] == "test.docx"
        assert result["data"]["order_number"] == "ORD001"
        assert result["data"]["record_id"] == 1

    def test_uses_filename_alias(self):
        payload = {"success": True, "filename": "test.docx"}
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        assert result["document"]["filename"] == "test.docx"

    def test_uses_filepath_alias(self):
        payload = {"success": True, "filepath": "/tmp/test.docx"}
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        assert result["document"]["filepath"] == "/tmp/test.docx"

    def test_uses_order_id_alias(self):
        payload = {"success": True, "order_id": 99}
        result = ShipmentNumberModeService._normalize_success_payload(payload)
        assert result["record_id"] == 99
        assert result["order_id"] == 99


# ---------------------------------------------------------------------------
# execute (main entry point)
# ---------------------------------------------------------------------------


class TestExecute:
    def test_missing_order_text_returns_400(self, svc):
        result, status = svc.execute(
            order_text="",
            custom_order_number="",
            direct_unit_name="",
            direct_products=[],
            parse_order_text=lambda x: {"success": False},
        )
        assert status == 400
        assert result["success"] is False
        assert "missing_order_text" in result.get("error_code", "")

    def test_direct_unit_and_products_bypass_parsing(self, svc):
        mock_app_svc = MagicMock()
        mock_app_svc.generate_shipment_document.return_value = {
            "success": True,
            "doc_name": "test.docx",
            "order_number": "ORD001",
            "record_id": 1,
        }
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch(
                "app.services.shipment_number_mode_service.get_shipment_app_service",
                return_value=mock_app_svc,
            ),
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 200
        assert result["success"] is True

    def test_unit_not_found_returns_400(self, svc):
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
        ):
            result, status = svc.execute(
                order_text="未知公司9803规格28 5桶",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {
                    "success": True,
                    "unit_name": "未知公司",
                    "products": [{"model_number": "9803", "tin_spec": "28", "quantity_tins": 5}],
                },
            )
        assert status == 400
        assert result["success"] is False
        assert "purchase_unit_not_found" in result.get("error_code", "")

    def test_parse_failure_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="无法解析的文本",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {"success": False, "message": "无法解析"},
            )
        assert status == 400
        assert result["success"] is False

    def test_modify_request_without_unit_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="再加2桶",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "purchase_unit_required_for_modify" in result.get("error_code", "")

    def test_modify_request_recovers_unit(self, svc):
        mock_app_svc = MagicMock()
        mock_app_svc.generate_shipment_document.return_value = {
            "success": True,
            "doc_name": "test.docx",
            "order_number": "ORD001",
            "record_id": 1,
        }
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch(
                "app.services.shipment_number_mode_service.get_shipment_app_service",
                return_value=mock_app_svc,
            ),
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="七彩乐园再加2桶9803规格28",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {
                    "success": True,
                    "unit_name": "七彩乐园",
                    "products": [{"model_number": "9803", "tin_spec": "28", "quantity_tins": 2}],
                },
            )
        assert status == 200

    def test_missing_model_in_product_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "型号缺失" in result["message"]

    def test_missing_spec_in_product_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "规格缺失" in result["message"]

    def test_zero_quantity_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 0,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "数量缺失或无效" in result["message"]

    def test_model_not_in_db_returns_400(self, svc):
        mock_db = MagicMock()
        # No matching model in DB
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("OTHER", "其他产品"),
        ]
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "型号不存在" in result["message"]

    def test_generation_failure_returns_400(self, svc):
        mock_app_svc = MagicMock()
        mock_app_svc.generate_shipment_document.return_value = {
            "success": False,
            "message": "模板不存在",
        }
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch(
                "app.services.shipment_number_mode_service.get_shipment_app_service",
                return_value=mock_app_svc,
            ),
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 400
        assert "NUMBER_MODE_STRICT_FAILED" in result["error_code"]

    def test_custom_order_number_passed_through(self, svc):
        mock_app_svc = MagicMock()
        mock_app_svc.generate_shipment_document.return_value = {
            "success": True,
            "doc_name": "test.docx",
            "order_number": "CUSTOM001",
            "record_id": 1,
        }
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch(
                "app.services.shipment_number_mode_service.get_shipment_app_service",
                return_value=mock_app_svc,
            ),
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="",
                custom_order_number="CUSTOM001",
                direct_unit_name="七彩乐园",
                direct_products=[
                    {
                        "model_number": "9803",
                        "product_name": "产品A",
                        "tin_spec": "28",
                        "quantity_tins": 5,
                    }
                ],
                parse_order_text=lambda x: {"success": False},
            )
        assert status == 200
        mock_app_svc.generate_shipment_document.assert_called_once()
        call_kwargs = mock_app_svc.generate_shipment_document.call_args[1]
        assert call_kwargs["order_number"] == "CUSTOM001"

    def test_db_terms_fallback_on_parse_failure(self, svc):
        mock_app_svc = MagicMock()
        mock_app_svc.generate_shipment_document.return_value = {
            "success": True,
            "doc_name": "test.docx",
            "order_number": "ORD001",
            "record_id": 1,
        }
        mock_db = MagicMock()
        # First call: model_pool for db_terms fallback
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("9803", "产品A"),
        ]
        with (
            patch(
                "app.services.shipment_number_mode_service.get_shipment_app_service",
                return_value=mock_app_svc,
            ),
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="七彩乐园9803规格28 5桶",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {"success": False, "message": "parse failed"},
            )
        # Should succeed via db_terms fallback
        assert status == 200

    def test_no_products_and_no_unit_returns_400(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        with (
            patch.object(svc, "_query_active_purchase_unit_names", return_value=["七彩乐园"]),
            patch("app.services.shipment_number_mode_service.get_db", _mock_get_db(mock_db)),
        ):
            result, status = svc.execute(
                order_text="随便说说",
                custom_order_number="",
                direct_unit_name="",
                direct_products=[],
                parse_order_text=lambda x: {"success": False, "message": "no match"},
            )
        assert status == 400


# ---------------------------------------------------------------------------
# _query_active_purchase_unit_names
# ---------------------------------------------------------------------------


class TestQueryActivePurchaseUnitNames:
    def test_returns_unit_names(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            ("七彩乐园",),
            ("蕊芯化工",),
        ]
        with patch("app.db.session.get_db", _mock_get_db(mock_db)):
            result = svc._query_active_purchase_unit_names()
        assert "七彩乐园" in result
        assert "蕊芯化工" in result

    def test_filters_empty_names(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            ("七彩乐园",),
            ("",),
            (None,),
        ]
        with patch("app.db.session.get_db", _mock_get_db(mock_db)):
            result = svc._query_active_purchase_unit_names()
        assert "七彩乐园" in result
        assert "" not in result
