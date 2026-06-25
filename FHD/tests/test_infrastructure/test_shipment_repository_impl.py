"""Branch coverage for app.infrastructure.repositories.shipment_repository_impl.

Covers save (update vs insert), find_by_order_number int parse, delete (0/8 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_db_record(**overrides):
    m = MagicMock()
    defaults = {"id": 1, "purchase_unit": "Acme", "status": "pending"}
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


class TestSave:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_save_new_shipment_no_id(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None

        def _refresh(obj):
            obj.id = 42

        mock_db.refresh.side_effect = _refresh
        shipment = MagicMock()
        shipment.id = None  # no id → insert path

        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_db",
                return_value={"purchase_unit": "Acme", "status": "pending"},
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=shipment,
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.ShipmentRecord"
            ) as MockRec,
        ):
            MockRec.return_value = _make_db_record(id=42)
            result = self._svc().save(shipment)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        assert shipment.id == 42

    def test_save_existing_shipment_updates(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        existing = _make_db_record(id=5)
        mock_q.first.return_value = existing

        mock_db.refresh.side_effect = lambda obj: None
        shipment = MagicMock()
        shipment.id = 5  # has id → update path

        domain_result = MagicMock()
        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_db",
                return_value={"purchase_unit": "Updated", "status": "shipped"},
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=domain_result,
            ),
        ):
            result = self._svc().save(shipment)
        # Should update existing record, not add new
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
        assert existing.purchase_unit == "Updated"
        assert existing.status == "shipped"
        assert result is domain_result

    def test_save_with_id_but_no_existing_inserts(self):
        # shipment.id is set but no existing record found → insert path
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None

        def _refresh(obj):
            obj.id = 99

        mock_db.refresh.side_effect = _refresh
        shipment = MagicMock()
        shipment.id = 99

        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_db",
                return_value={"purchase_unit": "Acme"},
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=shipment,
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.ShipmentRecord"
            ) as MockRec,
        ):
            MockRec.return_value = _make_db_record(id=99)
            result = self._svc().save(shipment)
        mock_db.add.assert_called_once()


class TestFindById:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_found(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = _make_db_record(id=1)
        domain = MagicMock()
        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=domain,
            ),
        ):
            result = self._svc().find_by_id(1)
        assert result is domain

    def test_not_found(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        with patch(
            "app.infrastructure.repositories.shipment_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().find_by_id(999)
        assert result is None


class TestFindByOrderNumber:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_valid_integer_string(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = _make_db_record(id=42)
        domain = MagicMock()
        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=domain,
            ),
        ):
            result = self._svc().find_by_order_number("42")
        assert result is domain

    def test_non_integer_string_returns_none(self):
        with patch(
            "app.infrastructure.repositories.shipment_repository_impl.get_db",
            return_value=_mock_db_ctx(MagicMock()),
        ):
            result = self._svc().find_by_order_number("not-a-number")
        assert result is None


class TestFindAll:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_returns_list(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.offset.return_value = mock_q
        mock_q.all.return_value = [_make_db_record(id=1), _make_db_record(id=2)]
        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                side_effect=lambda r: MagicMock(id=r.id),
            ),
        ):
            result = self._svc().find_all(page=2, per_page=10)
        assert len(result) == 2
        # offset = (2-1) * 10 = 10
        mock_q.offset.assert_called_once_with(10)


class TestFindByUnit:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_returns_list(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = [_make_db_record()]
        with (
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.repositories.shipment_repository_impl.shipment_to_domain",
                return_value=MagicMock(),
            ),
        ):
            result = self._svc().find_by_unit("Acme")
        assert len(result) == 1


class TestDelete:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_delete_existing(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = _make_db_record(id=1)
        with patch(
            "app.infrastructure.repositories.shipment_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().delete(1)
        assert result is True
        mock_db.delete.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_delete_nonexistent(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        with patch(
            "app.infrastructure.repositories.shipment_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().delete(999)
        assert result is False
        mock_db.delete.assert_not_called()


class TestCount:
    def _svc(self):
        from app.infrastructure.repositories.shipment_repository_impl import (
            SQLAlchemyShipmentRepository,
        )

        return SQLAlchemyShipmentRepository()

    def test_count(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.count.return_value = 42
        with patch(
            "app.infrastructure.repositories.shipment_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = self._svc().count()
        assert result == 42
