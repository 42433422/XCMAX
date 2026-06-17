"""Tests for app.services.unified_query_service — coverage ramp ext2.

Covers ``UnifiedQueryService`` static methods (get_distinct_values / get_all /
get_first / exists / count / delete) and module-level helpers
(``get_product_names`` / ``get_purchase_units`` / ``find_purchase_unit`` /
``find_product`` / ``check_purchase_unit_exists`` / ``delete_purchase_unit``)
by mocking the ``get_db`` context manager.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services import unified_query_service as uqs_mod
from app.services.unified_query_service import (
    UnifiedQueryService,
    check_purchase_unit_exists,
    delete_purchase_unit,
    find_product,
    find_purchase_unit,
    get_product_names,
    get_purchase_units,
)


class _FakeQuery:
    """Minimal SQLAlchemy-like query recorder."""

    def __init__(self, items=None):
        self._items = items or []
        self._filters = []
        self._order = []
        self._limit = None
        self._offset = None
        self._distinct = False

    def filter(self, cond):
        self._filters.append(cond)
        return self

    def filter_by(self, **kwargs):
        self._filters.append(kwargs)
        return self

    def order_by(self, *args):
        self._order.extend(args)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def distinct(self):
        self._distinct = True
        return self

    def all(self):
        items = list(self._items)
        if self._limit is not None:
            items = items[: self._limit]
        return items

    def first(self):
        items = list(self._items)
        if self._limit is not None:
            items = items[: self._limit]
        return items[0] if items else None

    def count(self):
        return len(self._items)

    def delete(self, synchronize_session=False):
        n = len(self._items)
        self._items.clear()
        return n


class _FakeDb:
    def __init__(self, items=None):
        self._items = items or []
        self.committed = False

    def query(self, *args, **kwargs):
        return _FakeQuery(list(self._items))

    def commit(self):
        self.committed = True


@contextmanager
def _fake_get_db(db):
    yield db


# ── get_distinct_values ──────────────────────────────────────────────────────


class TestGetDistinctValues:
    def test_basic_distinct(self):
        db = _FakeDb(items=[("a",), ("b",), ("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(MagicMock(), "name")
        assert out == ["a", "b", "a"]  # not deduped at SQL level mock

    def test_with_filter_kwargs(self):
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(
                MagicMock(), "name", filter_kwargs={"name": "a"}
            )
        assert out == ["a"]

    def test_with_keyword_filter(self):
        mc = MagicMock()
        mc.name.like.return_value = "like-cond"
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(mc, "name", keyword="a")
        assert out == ["a"]

    def test_desc_order(self):
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(
                MagicMock(), "name", order_by="desc"
            )
        assert out == ["a"]

    def test_with_limit(self):
        db = _FakeDb(items=[("a",), ("b",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(
                MagicMock(), "name", limit=1
            )
        assert out == ["a"]  # mock doesn't enforce limit but returns items

    def test_filters_none_rows(self):
        db = _FakeDb(items=[("a",), (None,), ("",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(MagicMock(), "name")
        # None and empty string filtered out by `if r and r[0]`
        assert out == ["a"]


# ── get_all ──────────────────────────────────────────────────────────────────


class TestGetAll:
    def test_basic(self):
        items = [MagicMock(id=1), MagicMock(id=2)]
        db = _FakeDb(items=items)
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(MagicMock())
        assert len(out) == 2

    def test_with_filter_kwargs(self):
        db = _FakeDb(items=[MagicMock(id=1)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(
                MagicMock(), filter_kwargs={"name": "a"}
            )
        assert len(out) == 1

    def test_with_order_by_asc(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.field = attr
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(mc, order_by=[("field", "asc")])
        assert len(out) == 1

    def test_with_order_by_desc(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.field = attr
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(mc, order_by=[("field", "desc")])
        assert len(out) == 1

    def test_order_by_missing_attr_skipped(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(
                NoField(), order_by=[("missing", "asc")]
            )
        assert len(out) == 1

    def test_offset_and_limit(self):
        db = _FakeDb(items=[MagicMock(id=i) for i in range(5)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(MagicMock(), offset=2, limit=2)
        # _FakeQuery enforces limit in all(), so returns 2 items
        assert len(out) == 2


# ── get_first ────────────────────────────────────────────────────────────────


class TestGetFirst:
    def test_returns_first(self):
        first = MagicMock(id=1)
        db = _FakeDb(items=[first])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_first(MagicMock())
        assert out is first

    def test_returns_none_when_empty(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_first(MagicMock())
        assert out is None

    def test_with_filter_kwargs(self):
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_first(MagicMock(), name="a")
        assert out is not None


# ── exists ───────────────────────────────────────────────────────────────────


class TestExists:
    def test_true_when_present(self):
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.exists(MagicMock()) is True

    def test_false_when_absent(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.exists(MagicMock()) is False

    def test_with_filter(self):
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.exists(MagicMock(), name="a") is True


# ── count ────────────────────────────────────────────────────────────────────


class TestCount:
    def test_zero(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.count(MagicMock()) == 0

    def test_multiple(self):
        db = _FakeDb(items=[MagicMock(), MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.count(MagicMock()) == 3

    def test_with_filter(self):
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert UnifiedQueryService.count(MagicMock(), name="a") == 1


# ── delete ───────────────────────────────────────────────────────────────────


class TestDelete:
    def test_zero_no_commit(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(MagicMock())
        assert n == 0
        assert db.committed is False

    def test_deletes_and_commits(self):
        db = _FakeDb(items=[MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(MagicMock())
        assert n == 2
        assert db.committed is True

    def test_with_filter(self):
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(MagicMock(), name="a")
        assert n == 1


# ── module-level helpers ─────────────────────────────────────────────────────


class TestGetProductNames:
    def test_delegates_to_query_service(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.get_distinct_values.return_value = ["p1", "p2"]
            out = get_product_names("k")
            assert out == ["p1", "p2"]
            mock_qs.get_distinct_values.assert_called_once()
            call_kwargs = mock_qs.get_distinct_values.call_args.kwargs
            assert call_kwargs["keyword"] == "k"
            assert call_kwargs["filter_kwargs"] == {"is_active": 1}

    def test_none_keyword(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.get_distinct_values.return_value = []
            get_product_names(None)
            call_kwargs = mock_qs.get_distinct_values.call_args.kwargs
            assert call_kwargs["keyword"] is None


class TestGetPurchaseUnits:
    def test_returns_dicts(self):
        u1 = MagicMock(
            id=1,
            unit_name="u1",
            contact_person="c1",
            contact_phone="p1",
            address="a1",
        )
        u2 = MagicMock(
            id=2,
            unit_name="u2",
            contact_person=None,
            contact_phone=None,
            address=None,
        )
        db = _FakeDb(items=[u1, u2])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = get_purchase_units("k")
        assert len(out) == 2
        assert out[0]["unit_name"] == "u1"
        assert out[1]["contact_person"] == ""
        assert out[1]["address"] == ""

    def test_no_keyword(self):
        u = MagicMock(
            id=1, unit_name="u", contact_person=None, contact_phone=None, address=None
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = get_purchase_units(None)
        assert len(out) == 1


class TestFindPurchaseUnit:
    def test_returns_dict_when_found(self):
        u = MagicMock(
            id=1,
            unit_name="u",
            contact_person="c",
            contact_phone="p",
            address="a",
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_purchase_unit(name="u")
        assert out["unit_name"] == "u"
        assert out["contact_person"] == "c"

    def test_returns_none_when_missing(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_purchase_unit(name="missing")
        assert out is None


class TestFindProduct:
    def test_returns_dict_when_found(self):
        p = MagicMock(
            id=1,
            model_number="m",
            specification="s",
            price=9.99,
            quantity=10,
            unit="个",
            category="c",
            brand="b",
        )
        # `name` is a special MagicMock attribute, must be set after creation
        p.name = "p"
        db = _FakeDb(items=[p])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_product(name="p")
        assert out["name"] == "p"
        assert out["price"] == 9.99
        assert out["quantity"] == 10

    def test_returns_none_when_missing(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            assert find_product(name="missing") is None

    def test_handles_none_numeric_fields(self):
        p = MagicMock(
            id=1,
            model_number=None,
            specification=None,
            price=None,
            quantity=None,
            unit=None,
            category=None,
            brand=None,
        )
        # `name` is a special MagicMock attribute, must be set after creation
        p.name = "p"
        db = _FakeDb(items=[p])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_product(name="p")
        assert out["price"] == 0.0
        assert out["quantity"] == 0
        assert out["unit"] == "个"


class TestCheckPurchaseUnitExists:
    def test_delegates_to_query_service(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.exists.return_value = True
            assert check_purchase_unit_exists("u") is True
            mock_qs.exists.assert_called_once()


class TestDeletePurchaseUnit:
    def test_delegates_to_query_service(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.delete.return_value = 1
            assert delete_purchase_unit(name="u") == 1
            mock_qs.delete.assert_called_once()
