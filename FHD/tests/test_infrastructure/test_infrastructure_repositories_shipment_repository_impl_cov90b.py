"""Second-wave coverage for shipment_repository_impl.

Targets the previously-uncovered branches of
``app.infrastructure.repositories.shipment_repository_impl.SQLAlchemyShipmentRepository``:

* ``_to_domain`` / ``_to_db_model`` mapper delegation (lines 13, 17).
* ``save`` — existing-record update branch, existing-not-found insert branch,
  and the no-id insert branch (lines 21-36).
* ``find_by_id`` — hit and miss (lines 40-42).
* ``find_by_order_number`` — numeric delegation and ValueError -> None
  (lines 46-50).
* ``find_all`` — pagination offset math + comprehension (lines 54-63).
* ``find_by_unit`` — filter + comprehension (lines 67-74).
* ``delete`` — found (True) and not-found (False) branches (lines 78-84).
* ``count`` — delegation (lines 88-89).

Every external dependency (``get_db`` context manager, the SQLAlchemy
``ShipmentRecord`` model, and the two mapper functions) is patched at the
module's import site so the test stays offline, deterministic, and free of any
real DB / ORM machinery.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.repositories.shipment_repository_impl import (
    SQLAlchemyShipmentRepository,
)

MODULE = "app.infrastructure.repositories.shipment_repository_impl"


@pytest.fixture
def repo():
    return SQLAlchemyShipmentRepository()


def _mock_db_ctx(mock_db):
    """Wrap a mock db in an object usable as ``with get_db() as db:``."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _first_returning(record):
    """db whose query(...).filter(...).first() yields ``record``."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = record
    return mock_db, mock_query


# --------------------------------------------------------------------------- #
# Mapper delegation (_to_domain / _to_db_model)  -- lines 13, 17
# --------------------------------------------------------------------------- #
class TestMapperDelegation:
    def test_to_domain_delegates_to_mapper(self, repo):
        db_record = MagicMock()
        sentinel = object()
        with patch(f"{MODULE}.shipment_to_domain", return_value=sentinel) as m:
            result = repo._to_domain(db_record)
        assert result is sentinel
        m.assert_called_once_with(db_record)

    def test_to_db_model_delegates_to_mapper(self, repo):
        shipment = MagicMock()
        payload = {"purchase_unit": "单位A", "status": "pending"}
        with patch(f"{MODULE}.shipment_to_db", return_value=payload) as m:
            result = repo._to_db_model(shipment)
        assert result == payload
        m.assert_called_once_with(shipment)


# --------------------------------------------------------------------------- #
# save() -- existing record update branch  (lines 21-29)
# --------------------------------------------------------------------------- #
class TestSaveUpdateExisting:
    def test_updates_existing_record_and_returns_domain(self, repo):
        shipment = MagicMock()
        shipment.id = 5

        existing = MagicMock()
        mock_db, mock_query = _first_returning(existing)

        domain_sentinel = object()
        payload = {"purchase_unit": "单位B", "status": "shipped"}

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_db_model", return_value=payload),
            patch.object(repo, "_to_domain", return_value=domain_sentinel) as to_domain,
        ):
            result = repo.save(shipment)

        # Each mapped field copied onto the existing ORM row.
        assert existing.purchase_unit == "单位B"
        assert existing.status == "shipped"
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(existing)
        to_domain.assert_called_once_with(existing)
        assert result is domain_sentinel
        # Insert path must NOT run.
        mock_db.add.assert_not_called()


# --------------------------------------------------------------------------- #
# save() -- has id but no existing row -> falls through to insert (lines 31-36)
# --------------------------------------------------------------------------- #
class TestSaveInsertWhenIdMissing:
    def test_id_set_but_not_found_inserts_new_record(self, repo):
        shipment = MagicMock()
        shipment.id = 99

        mock_db, _ = _first_returning(None)  # existing lookup misses

        new_row = MagicMock()
        new_row.id = 123
        payload = {"purchase_unit": "单位C", "status": "pending"}

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_db_model", return_value=payload),
            patch(f"{MODULE}.ShipmentRecord", return_value=new_row) as RecCls,
        ):
            result = repo.save(shipment)

        RecCls.assert_called_once_with(**payload)
        mock_db.add.assert_called_once_with(new_row)
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(new_row)
        # The new DB id is written back onto the domain object, which is returned.
        assert shipment.id == 123
        assert result is shipment


# --------------------------------------------------------------------------- #
# save() -- no id at all -> straight insert  (lines 31-36)
# --------------------------------------------------------------------------- #
class TestSaveInsertNew:
    def test_no_id_inserts_and_backfills_id(self, repo):
        shipment = MagicMock()
        shipment.id = None  # falsy -> skip the update block entirely

        mock_db = MagicMock()
        new_row = MagicMock()
        new_row.id = 7
        payload = {"purchase_unit": "单位D", "status": "pending"}

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_db_model", return_value=payload),
            patch(f"{MODULE}.ShipmentRecord", return_value=new_row),
        ):
            result = repo.save(shipment)

        # Never queried for an existing row because id was falsy.
        mock_db.query.assert_not_called()
        mock_db.add.assert_called_once_with(new_row)
        assert shipment.id == 7
        assert result is shipment


# --------------------------------------------------------------------------- #
# find_by_id() -- hit and miss  (lines 40-42)
# --------------------------------------------------------------------------- #
class TestFindById:
    def test_found_returns_domain(self, repo):
        record = MagicMock()
        mock_db, mock_query = _first_returning(record)
        domain_sentinel = object()

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain", return_value=domain_sentinel) as to_domain,
        ):
            result = repo.find_by_id(11)

        mock_db.query.assert_called_once()
        to_domain.assert_called_once_with(record)
        assert result is domain_sentinel

    def test_missing_returns_none(self, repo):
        mock_db, _ = _first_returning(None)
        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain") as to_domain,
        ):
            result = repo.find_by_id(404)

        assert result is None
        to_domain.assert_not_called()


# --------------------------------------------------------------------------- #
# find_by_order_number() -- numeric delegation + ValueError branch (lines 46-50)
# --------------------------------------------------------------------------- #
class TestFindByOrderNumber:
    def test_numeric_string_delegates_to_find_by_id(self, repo):
        sentinel = object()
        with patch.object(repo, "find_by_id", return_value=sentinel) as fbi:
            result = repo.find_by_order_number("42")
        fbi.assert_called_once_with(42)
        assert result is sentinel

    def test_non_numeric_returns_none(self, repo):
        with patch.object(repo, "find_by_id") as fbi:
            result = repo.find_by_order_number("ORDER-XYZ")
        assert result is None
        fbi.assert_not_called()


# --------------------------------------------------------------------------- #
# find_all() -- pagination offset + comprehension  (lines 54-63)
# --------------------------------------------------------------------------- #
class TestFindAll:
    def test_returns_mapped_list_with_offset(self, repo):
        rec_a, rec_b = MagicMock(), MagicMock()
        mock_db = MagicMock()
        chain = (
            mock_db.query.return_value.order_by.return_value.limit.return_value.offset.return_value
        )
        chain.all.return_value = [rec_a, rec_b]

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain", side_effect=lambda r: ("D", r)) as to_domain,
        ):
            result = repo.find_all(page=3, per_page=20)

        # offset = (page - 1) * per_page = 40
        limit_mock = mock_db.query.return_value.order_by.return_value.limit
        limit_mock.assert_called_once_with(20)
        limit_mock.return_value.offset.assert_called_once_with(40)
        assert result == [("D", rec_a), ("D", rec_b)]
        assert to_domain.call_count == 2

    def test_defaults_page_one_offset_zero_empty(self, repo):
        mock_db = MagicMock()
        chain = (
            mock_db.query.return_value.order_by.return_value.limit.return_value.offset.return_value
        )
        chain.all.return_value = []

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain") as to_domain,
        ):
            result = repo.find_all()

        limit_mock = mock_db.query.return_value.order_by.return_value.limit
        limit_mock.assert_called_once_with(20)
        limit_mock.return_value.offset.assert_called_once_with(0)
        assert result == []
        to_domain.assert_not_called()


# --------------------------------------------------------------------------- #
# find_by_unit() -- filter + comprehension  (lines 67-74)
# --------------------------------------------------------------------------- #
class TestFindByUnit:
    def test_returns_mapped_list(self, repo):
        rec = MagicMock()
        mock_db = MagicMock()
        chain = mock_db.query.return_value.filter.return_value.order_by.return_value
        chain.all.return_value = [rec]

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain", side_effect=lambda r: ("U", r)) as to_domain,
        ):
            result = repo.find_by_unit("采购单位甲")

        mock_db.query.return_value.filter.assert_called_once()
        assert result == [("U", rec)]
        to_domain.assert_called_once_with(rec)

    def test_empty_result(self, repo):
        mock_db = MagicMock()
        chain = mock_db.query.return_value.filter.return_value.order_by.return_value
        chain.all.return_value = []

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch.object(repo, "_to_domain") as to_domain,
        ):
            result = repo.find_by_unit("不存在单位")

        assert result == []
        to_domain.assert_not_called()


# --------------------------------------------------------------------------- #
# delete() -- found (True) and not-found (False)  (lines 78-84)
# --------------------------------------------------------------------------- #
class TestDelete:
    def test_found_deletes_and_returns_true(self, repo):
        record = MagicMock()
        mock_db, _ = _first_returning(record)

        with patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)):
            result = repo.delete(3)

        mock_db.delete.assert_called_once_with(record)
        mock_db.commit.assert_called_once()
        assert result is True

    def test_missing_returns_false(self, repo):
        mock_db, _ = _first_returning(None)

        with patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)):
            result = repo.delete(999)

        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()
        assert result is False


# --------------------------------------------------------------------------- #
# count() -- delegation  (lines 88-89)
# --------------------------------------------------------------------------- #
class TestCount:
    def test_returns_query_count(self, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 17

        with patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)):
            result = repo.count()

        assert result == 17
        mock_db.query.return_value.count.assert_called_once()
