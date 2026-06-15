"""Tests for app.services.document_templates.variables — pure helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.document_templates.variables import (
    _DEFAULT_TEMPLATE_SCOPE_RULES,
    _TERM_EQUIVALENTS,
    _build_scope_template_type_map,
    _get_equivalent_normalized_terms,
    _has_equivalent_term,
    _infer_business_scope,
    _normalize_term,
    _validate_required_terms,
)


# ========================= _normalize_term ===============================


class TestNormalizeTerm:
    def test_basic(self):
        assert _normalize_term("  产品型号  ") == "产品型号"

    def test_spaces_removed(self):
        assert _normalize_term("产 品 型 号") == "产品型号"

    def test_lower(self):
        assert _normalize_term("ABC") == "abc"

    def test_none(self):
        assert _normalize_term(None) == ""

    def test_empty(self):
        assert _normalize_term("") == ""


# ========================= _get_equivalent_normalized_terms ==============


class TestGetEquivalentNormalizedTerms:
    def test_known_term(self):
        result = _get_equivalent_normalized_terms("产品型号")
        assert "产品型号" in result
        assert "型号" in result

    def test_unknown_term(self):
        result = _get_equivalent_normalized_terms("自定义字段")
        assert "自定义字段" in result

    def test_empty(self):
        result = _get_equivalent_normalized_terms("")
        assert isinstance(result, list)


# ========================= _has_equivalent_term ==========================


class TestHasEquivalentTerm:
    def test_match(self):
        extracted = {"型号", "规格"}
        assert _has_equivalent_term(extracted, "产品型号") is True

    def test_no_match(self):
        extracted = {"名称", "地址"}
        assert _has_equivalent_term(extracted, "产品型号") is False

    def test_empty_set(self):
        assert _has_equivalent_term(set(), "产品型号") is False

    def test_not_set(self):
        assert _has_equivalent_term(["型号"], "产品型号") is False


# ========================= _validate_required_terms ======================


class TestValidateRequiredTerms:
    def test_orders_scope_match(self):
        cells = {}
        fields = [
            {"label": "产品型号", "name": "model", "value": ""},
            {"label": "产品名称", "name": "name", "value": ""},
            {"label": "数量", "name": "qty", "value": ""},
            {"label": "单价", "name": "price", "value": ""},
            {"label": "金额", "name": "amount", "value": ""},
        ]
        ok, missing = _validate_required_terms(cells, fields, "orders")
        assert ok is True
        assert missing == []

    def test_orders_scope_missing(self):
        cells = {}
        fields = [
            {"label": "产品名称", "name": "name", "value": ""},
        ]
        ok, missing = _validate_required_terms(cells, fields, "orders")
        assert ok is False
        assert len(missing) > 0

    def test_unknown_scope(self):
        ok, missing = _validate_required_terms({}, [], "unknown_scope")
        assert ok is True
        assert missing == []

    def test_cells_contribute_terms(self):
        cells = {"A1": {"value": "产品型号"}, "B1": {"value": "产品名称"}}
        fields = [
            {"label": "数量", "name": "qty", "value": ""},
            {"label": "单价", "name": "price", "value": ""},
            {"label": "金额", "name": "amount", "value": ""},
        ]
        ok, missing = _validate_required_terms(cells, fields, "orders")
        assert ok is True


# ========================= _build_scope_template_type_map ================


class TestBuildScopeTemplateTypeMap:
    def test_basic(self):
        result = _build_scope_template_type_map()
        assert "出货明细" in result
        assert result["出货明细"] == "orders"
        assert "产品目录" in result

    def test_legacy_aliases(self):
        result = _build_scope_template_type_map()
        assert "发货单" in result
        assert result["发货单"] == "orders"


# ========================= _infer_business_scope =========================


class TestInferBusinessScope:
    def test_orders(self):
        assert _infer_business_scope("出货明细") == "orders"

    def test_products(self):
        assert _infer_business_scope("产品目录") == "products"

    def test_legacy(self):
        assert _infer_business_scope("发货单") == "orders"

    def test_unknown(self):
        assert _infer_business_scope("未知类型") == ""

    def test_empty(self):
        assert _infer_business_scope("") == ""

    def test_none(self):
        assert _infer_business_scope(None) == ""


# ========================= _DEFAULT_TEMPLATE_SCOPE_RULES ================


class TestDefaultTemplateScopeRules:
    def test_has_required_scopes(self):
        assert "orders" in _DEFAULT_TEMPLATE_SCOPE_RULES
        assert "products" in _DEFAULT_TEMPLATE_SCOPE_RULES
        assert "customers" in _DEFAULT_TEMPLATE_SCOPE_RULES

    def test_each_scope_has_required_terms(self):
        for scope_key, meta in _DEFAULT_TEMPLATE_SCOPE_RULES.items():
            assert "templateType" in meta
            assert "requiredTerms" in meta
            assert len(meta["requiredTerms"]) > 0
