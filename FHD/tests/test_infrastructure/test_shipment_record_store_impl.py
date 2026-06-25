"""Branch coverage for app.infrastructure.persistence.shipment_record_store_impl.

Covers record_document_generation product-field fallback branches (0/8 branches).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _setup_db_with_record(record_id=99):
    mock_db = MagicMock()

    def _refresh(obj):
        obj.id = record_id

    mock_db.refresh.side_effect = _refresh
    return mock_db


class TestRecordDocumentGeneration:
    def _svc(self):
        from app.infrastructure.persistence.shipment_record_store_impl import (
            SQLAlchemyShipmentRecordStore,
        )

        return SQLAlchemyShipmentRecordStore()

    def test_full_product_fields(self):
        mock_db = _setup_db_with_record(7)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[
                    {
                        "name": "Widget",
                        "model_number": "M1",
                        "quantity_tins": 4,
                        "tin_spec": 2.5,
                        "quantity_kg": 10.0,
                        "unit_price": 5.0,
                        "amount": 50.0,
                    }
                ],
                document_result={
                    "doc_name": "doc.pdf",
                    "file_path": "/tmp/doc.pdf",
                    "order_number": "ORD-1",
                    "total_amount": 50.0,
                    "total_quantity": 10.0,
                },
            )
        assert result["success"] is True
        assert result["record_id"] == 7

    def test_empty_products_uses_defaults(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=None,
                products=[],
                document_result={},
            )
        assert result["success"] is True

    def test_none_products_uses_defaults(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=None,
                products=None,
                document_result={},
            )
        assert result["success"] is True

    def test_product_name_fallback_to_product_name_key(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"product_name": "FromAltKey"}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.product_name == "FromAltKey"

    def test_model_number_fallback_to_chinese_key(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"型号": "X-100"}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.model_number == "X-100"

    def test_quantity_tins_fallback_to_quantity(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"quantity": 7}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.quantity_tins == 7

    def test_quantity_kg_computed_from_tins_and_spec(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"quantity_tins": 4, "tin_spec": 2.5}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.quantity_kg == 10.0

    def test_quantity_kg_provided_directly_skips_computation(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"quantity_tins": 4, "tin_spec": 2.5, "quantity_kg": 99.0}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        # quantity_kg provided directly → not computed from tins * spec
        assert added.quantity_kg == 99.0

    def test_amount_computed_from_unit_price_and_kg(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"quantity_tins": 4, "tin_spec": 2.5, "unit_price": 3.0}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        # quantity_kg = 4 * 2.5 = 10.0; amount = 3.0 * 10.0 = 30.0
        assert added.amount == 30.0

    def test_amount_provided_directly_skips_computation(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"quantity_tins": 4, "tin_spec": 2.5, "amount": 77.0}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        # amount provided directly → not computed
        assert added.amount == 77.0

    def test_unit_price_fallback_to_price_key(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"price": 9.0}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.unit_price == 9.0

    def test_tin_spec_fallback_to_spec_key(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{"spec": 5.0}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.tin_spec == 5.0

    def test_product_name_falls_back_to_unit_name(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{}],
                document_result={},
            )
        added = mock_db.add.call_args[0][0]
        assert added.product_name == "Acme"

    def test_raw_text_passed_through(self):
        mock_db = _setup_db_with_record(1)
        with patch(
            "app.infrastructure.persistence.shipment_record_store_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            self._svc().record_document_generation(
                unit_name="Acme",
                unit_id=1,
                products=[{}],
                document_result={},
                raw_text="some raw text",
            )
        added = mock_db.add.call_args[0][0]
        assert added.raw_text == "some raw text"
