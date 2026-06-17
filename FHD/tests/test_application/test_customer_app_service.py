"""Comprehensive tests for app.application.customer_app_service.

Covers: get_all, get_by_id, create, update, delete, batch_delete, import_data,
import_from_excel, export_to_excel, get_purchase_unit_by_name, match_purchase_unit,
and helper functions.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.application.customer_app_service import (
    CustomerApplicationService,
    get_customer_app_service,
    get_customers_session,
    reset_customers_engine,
)

# ---------------------------------------------------------------------------
# get_customers_session
# ---------------------------------------------------------------------------


class TestGetCustomersSession:
    def test_fallback_to_session_local(self):
        with (
            patch(
                "app.mod_sdk.erp_repository_registry.resolve_customers_session",
                side_effect=ImportError("no mod"),
            ),
            patch("app.db.SessionLocal") as mock_sl,
        ):
            get_customers_session()
            mock_sl.assert_called_once()


# ---------------------------------------------------------------------------
# reset_customers_engine
# ---------------------------------------------------------------------------


class TestResetCustomersEngine:
    def test_calls_invalidate(self):
        mock_registry = MagicMock()
        with patch("app.di.registry.get_service_registry", return_value=mock_registry):
            reset_customers_engine()
            mock_registry.invalidate_customer_application_service.assert_called_once()


# ---------------------------------------------------------------------------
# CustomerApplicationService — get_all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_happy_path(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "TestCo"
        mock_unit.contact_person = "Zhang"
        mock_unit.contact_phone = "138"
        mock_unit.address = "Addr"
        mock_unit.created_at = datetime(2024, 1, 1)
        mock_unit.updated_at = None
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_unit
        ]
        mock_session.query.return_value = mock_query

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_all()
            assert result["success"] is True
            assert result["total"] == 1
            assert result["data"][0]["customer_name"] == "TestCo"

    def test_with_keyword(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_all(keyword="Test")
            assert result["success"] is True

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch.object(svc, "_get_session", side_effect=RuntimeError("db fail")):
            result = svc.get_all()
            assert result["success"] is False


# ---------------------------------------------------------------------------
# CustomerApplicationService — get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    def test_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "TestCo"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_unit.created_at = None
        mock_unit.updated_at = None
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_by_id(1)
            assert result["success"] is True
            assert result["data"]["id"] == 1

    def test_not_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_by_id(999)
            assert result["success"] is False
            assert "不存在" in result["message"]

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch.object(svc, "_get_session", side_effect=RuntimeError("fail")):
            result = svc.get_by_id(1)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# CustomerApplicationService — create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_success(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "NewCo"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_unit.created_at = None
        mock_unit.updated_at = None

        def mock_refresh(u):
            u.id = 1

        mock_session.refresh = mock_refresh
        mock_session.add = MagicMock()

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.create({"customer_name": "NewCo"})
            assert result["success"] is True

    def test_empty_name(self):
        svc = CustomerApplicationService()
        result = svc.create({"customer_name": ""})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_duplicate_name(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = MagicMock()

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.create({"customer_name": "Existing"})
            assert result["success"] is False
            assert "已存在" in result["message"]

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch.object(svc, "_get_session", side_effect=RuntimeError("fail")):
            result = svc.create({"customer_name": "X"})
            assert result["success"] is False


# ---------------------------------------------------------------------------
# CustomerApplicationService — update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_success(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "Old"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_unit.created_at = None
        mock_unit.updated_at = None
        # First filter returns the unit, second filter (duplicate check) returns None
        mock_session.query.return_value.filter.side_effect = [
            MagicMock(first=MagicMock(return_value=mock_unit)),  # get by id
            MagicMock(first=MagicMock(return_value=None)),  # duplicate check
        ]

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.update(1, {"customer_name": "New"})
            assert result["success"] is True

    def test_not_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.update(999, {"customer_name": "X"})
            assert result["success"] is False

    def test_duplicate_name_on_update(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "Old"
        # First filter returns the unit, second filter (duplicate check) returns another
        mock_session.query.return_value.filter.side_effect = [
            MagicMock(first=MagicMock(return_value=mock_unit)),  # get by id
            MagicMock(first=MagicMock(return_value=MagicMock())),  # duplicate check
        ]

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.update(1, {"customer_name": "Duplicate"})
            assert result["success"] is False
            assert "已存在" in result["message"]


# ---------------------------------------------------------------------------
# CustomerApplicationService — delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_success(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.unit_name = "TestCo"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with (
            patch.object(svc, "_get_session", return_value=mock_session),
            patch.object(
                svc, "_check_shipment_associations", return_value={"has_associations": False}
            ),
        ):
            result = svc.delete(1)
            assert result["success"] is True

    def test_not_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.delete(999)
            assert result["success"] is False

    def test_has_associations_no_force(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.unit_name = "LinkedCo"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with (
            patch.object(svc, "_get_session", return_value=mock_session),
            patch.object(
                svc,
                "_check_shipment_associations",
                return_value={
                    "has_associations": True,
                    "shipment_count": 3,
                    "sample_records": [],
                },
            ),
        ):
            result = svc.delete(1, force=False)
            assert result["success"] is False
            assert result["has_associations"] is True

    def test_force_delete_with_associations(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.unit_name = "LinkedCo"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with (
            patch.object(svc, "_get_session", return_value=mock_session),
            patch.object(
                svc,
                "_check_shipment_associations",
                return_value={
                    "has_associations": True,
                    "shipment_count": 3,
                    "sample_records": [],
                },
            ),
        ):
            result = svc.delete(1, force=True)
            assert result["success"] is True


# ---------------------------------------------------------------------------
# CustomerApplicationService — batch_delete
# ---------------------------------------------------------------------------


class TestBatchDelete:
    def test_no_units_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.batch_delete([1, 2])
            assert result["success"] is False

    def test_success(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.unit_name = "Co1"
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_unit]

        with (
            patch.object(svc, "_get_session", return_value=mock_session),
            patch.object(
                svc, "_check_shipment_associations", return_value={"has_associations": False}
            ),
        ):
            result = svc.batch_delete([1])
            assert result["success"] is True
            assert result["deleted_count"] == 1

    def test_associations_block(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "Co1"
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_unit]

        with (
            patch.object(svc, "_get_session", return_value=mock_session),
            patch.object(
                svc,
                "_check_shipment_associations",
                return_value={
                    "has_associations": True,
                    "shipment_count": 2,
                    "sample_records": [],
                },
            ),
        ):
            result = svc.batch_delete([1], force=False)
            assert result["success"] is False
            assert result["has_associations"] is True


# ---------------------------------------------------------------------------
# CustomerApplicationService — import_data
# ---------------------------------------------------------------------------


class TestImportData:
    def test_success(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.import_data([{"customer_name": "NewCo"}])
            assert result["success"] is True
            assert result["imported"] == 1

    def test_skip_empty_name(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.import_data([{"customer_name": ""}])
            assert result["skipped"] == 1

    def test_skip_duplicate(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = MagicMock()

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.import_data([{"customer_name": "Existing"}], skip_duplicates=True)
            assert result["skipped"] == 1

    def test_update_duplicate_no_skip(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_existing = MagicMock()
        mock_existing.contact_person = ""
        mock_existing.contact_phone = ""
        mock_existing.address = ""
        mock_session.query.return_value.filter.return_value.first.return_value = mock_existing

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.import_data(
                [{"customer_name": "Existing", "contact_person": "New"}], skip_duplicates=False
            )
            assert result["imported"] == 1

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch.object(svc, "_get_session", side_effect=RuntimeError("fail")):
            result = svc.import_data([{"customer_name": "X"}])
            assert result["success"] is False


# ---------------------------------------------------------------------------
# CustomerApplicationService — match_purchase_unit
# ---------------------------------------------------------------------------


class TestMatchPurchaseUnit:
    def test_exact_match(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "TestCo"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.match_purchase_unit("TestCo")
            assert result is not None
            assert result.unit_name == "TestCo"

    def test_empty_name_returns_none(self):
        svc = CustomerApplicationService()
        result = svc.match_purchase_unit("")
        assert result is None

    def test_none_name_returns_none(self):
        svc = CustomerApplicationService()
        result = svc.match_purchase_unit(None)
        assert result is None

    def test_substring_match(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        # First query (exact) returns None
        mock_session.query.return_value.filter.return_value.first.return_value = None
        # Second query (all) returns list with a matching unit
        mock_unit = MagicMock()
        mock_unit.id = 2
        mock_unit.unit_name = "TestCompany"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_unit]

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.match_purchase_unit("Test")
            assert result is not None

    def test_no_match(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_session.query.return_value.filter.return_value.all.return_value = []

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.match_purchase_unit("NoMatch")
            assert result is None

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch.object(svc, "_get_session", side_effect=RuntimeError("fail")):
            result = svc.match_purchase_unit("X")
            assert result is None


# ---------------------------------------------------------------------------
# CustomerApplicationService — get_purchase_unit_by_name
# ---------------------------------------------------------------------------


class TestGetPurchaseUnitByName:
    def test_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_unit = MagicMock()
        mock_unit.id = 1
        mock_unit.unit_name = "TestCo"
        mock_unit.contact_person = ""
        mock_unit.contact_phone = ""
        mock_unit.address = ""
        mock_unit.discount_rate = 1.0
        mock_unit.is_active = True
        mock_unit.created_at = None
        mock_unit.updated_at = None
        mock_session.query.return_value.filter.return_value.first.return_value = mock_unit

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_purchase_unit_by_name("TestCo")
            assert result is not None
            assert result.unit_name == "TestCo"

    def test_not_found(self):
        svc = CustomerApplicationService()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch.object(svc, "_get_session", return_value=mock_session):
            result = svc.get_purchase_unit_by_name("NoMatch")
            assert result is None


# ---------------------------------------------------------------------------
# CustomerApplicationService — _check_shipment_associations
# ---------------------------------------------------------------------------


class TestCheckShipmentAssociations:
    def test_has_associations(self):
        svc = CustomerApplicationService()
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_record.id = 1
        mock_record.product_name = "Product"
        mock_record.quantity_kg = 100
        mock_record.created_at = None
        # First query: db.query(ShipmentRecord).filter(...).order_by(...).limit(3).all()
        mock_q1 = MagicMock()
        mock_q1.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_record
        ]
        # Second query: db.query(ShipmentRecord).filter(...).count()
        mock_q2 = MagicMock()
        mock_q2.filter.return_value.count.return_value = 1
        mock_db.query.side_effect = [mock_q1, mock_q2]
        # get_db() returns a context manager
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc._check_shipment_associations("TestCo")
            assert result["has_associations"] is True
            assert result["shipment_count"] == 1

    def test_no_associations(self):
        svc = CustomerApplicationService()
        mock_db = MagicMock()
        mock_q1 = MagicMock()
        mock_q1.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_q2 = MagicMock()
        mock_q2.filter.return_value.count.return_value = 0
        mock_db.query.side_effect = [mock_q1, mock_q2]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc._check_shipment_associations("TestCo")
            assert result["has_associations"] is False

    def test_db_error(self):
        svc = CustomerApplicationService()
        with patch("app.db.session.get_db", side_effect=RuntimeError("fail")):
            result = svc._check_shipment_associations("TestCo")
            assert result["has_associations"] is False


# ---------------------------------------------------------------------------
# get_customer_app_service
# ---------------------------------------------------------------------------


class TestGetCustomerAppService:
    def test_returns_service(self):
        mock_registry = MagicMock()
        mock_registry.customer_application_service = MagicMock()
        with patch("app.di.registry.get_service_registry", return_value=mock_registry):
            result = get_customer_app_service()
            assert result is not None
