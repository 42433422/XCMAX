"""Tests for app.services.kitten_business_snapshot — business data snapshot builder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.kitten_business_snapshot import (
    _fmt_dt,
    _iso_now,
    build_kitten_business_snapshot,
)

# ---------------------------------------------------------------------------
# _iso_now
# ---------------------------------------------------------------------------


class TestIsoNow:
    def test_returns_iso_string(self):
        result = _iso_now()
        assert isinstance(result, str)
        assert "T" in result or "+" in result

    def test_no_microseconds(self):
        result = _iso_now()
        # Should not have fractional seconds beyond whole seconds
        assert (
            "." not in result.split("+")[0].split("Z")[0].split("T")[-1] or result.count(".") == 0
        )


# ---------------------------------------------------------------------------
# _fmt_dt
# ---------------------------------------------------------------------------


class TestFmtDt:
    def test_none_returns_empty(self):
        assert _fmt_dt(None) == ""

    def test_datetime_isoformat(self):
        from datetime import UTC, datetime

        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = _fmt_dt(dt)
        assert "2024" in result
        assert "10:30" in result

    def test_string_passthrough(self):
        assert _fmt_dt("2024-01-15") == "2024-01-15"

    def test_integer_passthrough(self):
        assert _fmt_dt(42) == "42"

    def test_isoformat_error_falls_back(self):
        class BadDatetime:
            def isoformat(self):
                raise RuntimeError("bad isoformat")

        result = _fmt_dt(BadDatetime())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# build_kitten_business_snapshot — uses lazy imports inside function body
# ---------------------------------------------------------------------------


def _patch_materials(side_effect=None, return_value=None):
    """Patch the lazy import of get_material_application_service inside the function."""
    mock_svc = MagicMock()
    if side_effect:
        mock_svc.side_effect = side_effect
    if return_value:
        mock_svc.return_value = return_value
    return patch("app.application.get_material_application_service", mock_svc)


def _patch_products(side_effect=None, return_value=None):
    mock_svc = MagicMock()
    if side_effect:
        mock_svc.side_effect = side_effect
    if return_value:
        mock_svc.return_value = return_value
    return patch("app.bootstrap.get_products_service", mock_svc)


def _patch_shipments(side_effect=None, return_value=None):
    mock_svc = MagicMock()
    if side_effect:
        mock_svc.side_effect = side_effect
    if return_value:
        mock_svc.return_value = return_value
    return patch("app.bootstrap.get_shipment_app_service", mock_svc)


class TestBuildKittenBusinessSnapshot:
    def test_returns_success_structure(self):
        with (
            _patch_materials(side_effect=RuntimeError("no db")),
            _patch_products(side_effect=RuntimeError("no db")),
            _patch_shipments(side_effect=RuntimeError("no db")),
        ):
            result = build_kitten_business_snapshot()
        assert result["success"] is True
        assert "generated_at" in result
        assert "stats" in result
        assert "text" in result

    def test_materials_section_error(self):
        with (
            _patch_materials(side_effect=RuntimeError("db error")),
            _patch_products(side_effect=RuntimeError("db error")),
            _patch_shipments(side_effect=RuntimeError("db error")),
        ):
            result = build_kitten_business_snapshot()
        assert "materials_error" in result["stats"]
        assert "读取失败" in result["text"] or "materials_error" in result["stats"]

    def test_products_section_error(self):
        with (
            _patch_materials(side_effect=RuntimeError("db error")),
            _patch_products(side_effect=RuntimeError("db error")),
            _patch_shipments(side_effect=RuntimeError("db error")),
        ):
            result = build_kitten_business_snapshot()
        assert "products_error" in result["stats"]

    def test_shipments_section_error(self):
        with (
            _patch_materials(side_effect=RuntimeError("db error")),
            _patch_products(side_effect=RuntimeError("db error")),
            _patch_shipments(side_effect=RuntimeError("db error")),
        ):
            result = build_kitten_business_snapshot()
        assert "shipments_error" in result["stats"]

    def test_successful_materials_section(self):
        mock_mat_svc = MagicMock()
        mock_mat_svc.get_all_materials.return_value = {
            "data": [
                {
                    "name": "Paint A",
                    "category": "coating",
                    "quantity": 100,
                    "unit_price": 50.0,
                    "unit": "kg",
                    "supplier": "Supplier X",
                },
            ]
        }
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 10
        mock_db.query.return_value.filter.return_value.filter.return_value.scalar.return_value = 2
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.application.get_material_application_service", return_value=mock_mat_svc),
            patch("app.db.session.get_db", return_value=mock_db),
            _patch_products(side_effect=RuntimeError("no products")),
            _patch_shipments(side_effect=RuntimeError("no shipments")),
        ):
            result = build_kitten_business_snapshot()
        assert result["stats"]["materials_total"] == 10
        assert "Paint A" in result["text"]

    def test_text_truncation(self):
        with (
            _patch_materials(side_effect=RuntimeError("db error")),
            _patch_products(side_effect=RuntimeError("db error")),
            _patch_shipments(side_effect=RuntimeError("db error")),
        ):
            result = build_kitten_business_snapshot(max_text_chars=50)
        assert len(result["text"]) <= 74  # 50 + truncation suffix

    def test_shipments_with_records(self):
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = [
            {
                "purchase_unit": "Acme",
                "product_name": "Paint",
                "quantity_kg": 100,
                "quantity_tins": 10,
                "amount": 5000.0,
                "created_at": None,
            },
        ]
        with (
            _patch_materials(side_effect=RuntimeError("no mat")),
            _patch_products(side_effect=RuntimeError("no prod")),
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
        ):
            result = build_kitten_business_snapshot()
        assert result["stats"]["shipments_sample_count"] == 1
        assert result["stats"]["shipments_sample_amount_sum"] == 5000.0
        assert "Acme" in result["text"]
