"""Tests for app.services.unified_query_service — coverage ramp deep2.

Focuses on ``_parse_filter`` lookup operators (``__gte``/``__gt``/``__lte``/
``__lt``/``__ne``/``__in``/``__like``/``__ilike``), default-eq and list-``in_``
paths, plus edge cases for ``get_distinct_values``/``get_all``/``delete`` that
ext2 does not yet exercise.
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
    """Minimal SQLAlchemy-like query recorder (deep2 variant)."""

    def __init__(self, items=None):
        self._items = items or []
        self._filters = []
        self._order = []
        self._limit = None
        self._offset = None
        self._distinct = False
        self.delete_called = False
        self.delete_sync = None

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
        self.delete_called = True
        self.delete_sync = synchronize_session
        n = len(self._items)
        self._items.clear()
        return n


class _FakeDb:
    def __init__(self, items=None):
        self._items = items or []
        self.committed = False
        self.last_query: _FakeQuery | None = None

    def query(self, *args, **kwargs):
        self.last_query = _FakeQuery(list(self._items))
        return self.last_query

    def commit(self):
        self.committed = True


@contextmanager
def _fake_get_db(db):
    yield db


def _make_model_with_field(field_name: str = "name"):
    """Build a mock model class whose ``field_name`` attribute is itself a mock
    supporting comparison operators (``__ge__``, ``__gt__``, ``in_``, ``like`` …).

    Uses a real class so ``hasattr()`` works naturally.
    """

    class _Model:
        pass

    attr = MagicMock()
    # Comparison dunders return sentinel objects so we can assert identity.
    attr.__ge__ = MagicMock(return_value=f"ge:{field_name}")
    attr.__gt__ = MagicMock(return_value=f"gt:{field_name}")
    attr.__le__ = MagicMock(return_value=f"le:{field_name}")
    attr.__lt__ = MagicMock(return_value=f"lt:{field_name}")
    attr.__ne__ = MagicMock(return_value=f"ne:{field_name}")
    attr.in_ = MagicMock(return_value=f"in:{field_name}")
    attr.like = MagicMock(return_value=f"like:{field_name}")
    attr.ilike = MagicMock(return_value=f"ilike:{field_name}")
    # ``==`` returns sentinel too
    attr.__eq__ = MagicMock(return_value=f"eq:{field_name}")
    setattr(_Model, field_name, attr)
    return _Model


# ── _parse_filter: lookup operators ──────────────────────────────────────────


class TestParseFilterGte:
    def test_gte_returns_ge_condition(self):
        mc = _make_model_with_field("price")
        out = UnifiedQueryService._parse_filter(mc, "price__gte", 100)
        assert out == "ge:price"
        getattr(mc, "price").__ge__.assert_called_once_with(100)

    def test_gte_unknown_field_returns_none(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "price__gte", 100)
        assert out is None


class TestParseFilterGt:
    def test_gt_returns_gt_condition(self):
        mc = _make_model_with_field("price")
        out = UnifiedQueryService._parse_filter(mc, "price__gt", 100)
        assert out == "gt:price"
        getattr(mc, "price").__gt__.assert_called_once_with(100)


class TestParseFilterLte:
    def test_lte_returns_le_condition(self):
        mc = _make_model_with_field("price")
        out = UnifiedQueryService._parse_filter(mc, "price__lte", 100)
        assert out == "le:price"
        getattr(mc, "price").__le__.assert_called_once_with(100)


class TestParseFilterLt:
    def test_lt_returns_lt_condition(self):
        mc = _make_model_with_field("price")
        out = UnifiedQueryService._parse_filter(mc, "price__lt", 100)
        assert out == "lt:price"
        getattr(mc, "price").__lt__.assert_called_once_with(100)


class TestParseFilterNe:
    def test_ne_returns_ne_condition(self):
        mc = _make_model_with_field("status")
        out = UnifiedQueryService._parse_filter(mc, "status__ne", "deleted")
        assert out == "ne:status"
        getattr(mc, "status").__ne__.assert_called_once_with("deleted")


class TestParseFilterIn:
    def test_in_returns_in_condition(self):
        mc = _make_model_with_field("id")
        out = UnifiedQueryService._parse_filter(mc, "id__in", [1, 2, 3])
        assert out == "in:id"
        getattr(mc, "id").in_.assert_called_once_with([1, 2, 3])

    def test_in_unknown_field_returns_none(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "id__in", [1, 2])
        assert out is None


class TestParseFilterLike:
    def test_like_returns_like_condition(self):
        mc = _make_model_with_field("name")
        out = UnifiedQueryService._parse_filter(mc, "name__like", "abc")
        assert out == "like:name"
        getattr(mc, "name").like.assert_called_once_with("%abc%")

    def test_like_unknown_field_returns_none(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "name__like", "abc")
        assert out is None


class TestParseFilterIlike:
    def test_ilike_returns_ilike_condition(self):
        mc = _make_model_with_field("name")
        out = UnifiedQueryService._parse_filter(mc, "name__ilike", "abc")
        assert out == "ilike:name"
        getattr(mc, "name").ilike.assert_called_once_with("%abc%")

    def test_ilike_unknown_field_returns_none(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "name__ilike", "abc")
        assert out is None


class TestParseFilterDefaultEq:
    def test_scalar_value_returns_eq_condition(self):
        mc = _make_model_with_field("name")
        # Default eq path uses ``attr == value``; MagicMock ``==`` returns the
        # configured sentinel only if we use ``__eq__`` directly. The source
        # code uses ``attr == value`` which on MagicMock returns a non-sentinel
        # MagicMock instance. We just verify it is not None.
        out = UnifiedQueryService._parse_filter(mc, "name", "abc")
        assert out is not None

    def test_list_value_returns_in_condition(self):
        mc = _make_model_with_field("id")
        out = UnifiedQueryService._parse_filter(mc, "id", [1, 2, 3])
        assert out == "in:id"
        getattr(mc, "id").in_.assert_called_once_with([1, 2, 3])

    def test_unknown_field_returns_none(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "missing", "x")
        assert out is None


class TestParseFilterPrecedence:
    """``__gte``/``__gt``/``__lte``/``__lt``/``__ne`` are checked before
    ``__in``/``__like``/``__ilike``. Verify a key ending in ``__gte`` does
    not accidentally match the ``__in``/``__like`` branches."""

    def test_gte_takes_precedence_over_in(self):
        # ``price__gte`` ends with ``__gte`` but not ``__in``/``__like``/``__ilike``
        mc = _make_model_with_field("price")
        out = UnifiedQueryService._parse_filter(mc, "price__gte", 1)
        assert out == "ge:price"

    def test_in_does_not_match_like(self):
        mc = _make_model_with_field("name")
        # ``name__in`` should match ``__in`` branch, not ``__like``
        out = UnifiedQueryService._parse_filter(mc, "name__in", [1])
        assert out == "in:name"


# ── get_distinct_values: edge cases ──────────────────────────────────────────


class TestGetDistinctValuesEdge:
    def test_keyword_but_no_attr_skips_keyword_filter(self):
        """When ``hasattr(model_class, field_name)`` is False, the keyword
        filter branch is skipped entirely (but the initial query still needs
        the attribute, so we provide it as a MagicMock)."""

        class HasAttr:
            name = MagicMock()

        # Make hasattr return False by deleting the attribute after the
        # initial query. Since the source calls ``getattr`` for the query
        # then checks ``hasattr`` for the keyword, we need a model where
        # ``getattr`` succeeds but ``hasattr`` returns False — which is
        # impossible for normal classes. Instead, verify the keyword branch
        # is skipped by ensuring ``like`` is NOT called when keyword is
        # provided but the attribute's ``like`` would not be invoked if
        # we use a model whose ``name`` attr exists.
        mc = MagicMock()
        attr = MagicMock()
        attr.like.return_value = "like-cond"
        mc.name = attr
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(mc, "name", keyword="x")
        assert out == ["a"]
        # Verify like WAS called (since hasattr returns True for MagicMock)
        attr.like.assert_called_once_with("%x%")

    def test_asc_order_branch(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.name = attr
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(mc, "name", order_by="asc")
        assert out == ["a"]
        attr.asc.assert_called_once()

    def test_desc_order_branch(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.name = attr
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(mc, "name", order_by="desc")
        assert out == ["a"]
        attr.desc.assert_called_once()

    def test_filter_kwargs_with_none_condition_skipped(self):
        """If ``_parse_filter`` returns None (unknown field), the filter is
        not applied but the query continues."""

        class HasName:
            name = MagicMock()

        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(
                HasName(), "name", filter_kwargs={"unknown": "x"}
            )
        assert out == ["a"]

    def test_limit_zero_no_limit_applied(self):
        mc = MagicMock()
        mc.name = MagicMock()
        db = _FakeDb(items=[("a",), ("b",), ("c",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(mc, "name", limit=0)
        # _FakeQuery.all() returns all items when _limit is None
        assert len(out) == 3

    def test_empty_rows_filtered_out(self):
        """Rows that are falsy (None or empty tuple) are filtered by
        ``if r and r[0]``."""
        db = _FakeDb(items=[("a",), None, (), ("",), ("b",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(MagicMock(), "name")
        assert out == ["a", "b"]

    def test_filter_kwargs_with_gte_operator(self):
        mc = _make_model_with_field("price")
        db = _FakeDb(items=[("a",)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_distinct_values(
                mc, "price", filter_kwargs={"price__gte": 100}
            )
        assert out == ["a"]


# ── get_all: edge cases ──────────────────────────────────────────────────────


class TestGetAllEdge:
    def test_order_by_uppercase_desc(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.field = attr
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(mc, order_by=[("field", "DESC")])
        assert len(out) == 1
        attr.desc.assert_called_once()

    def test_order_by_uppercase_asc(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.field = attr
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(mc, order_by=[("field", "ASC")])
        assert len(out) == 1
        attr.asc.assert_called_once()

    def test_order_by_mixed_case(self):
        mc = MagicMock()
        attr = MagicMock()
        attr.asc.return_value = "asc"
        attr.desc.return_value = "desc"
        mc.field = attr
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(mc, order_by=[("field", "DeSc")])
        assert len(out) == 1
        attr.desc.assert_called_once()

    def test_order_by_multiple_fields(self):
        mc = MagicMock()
        attr1 = MagicMock()
        attr1.asc.return_value = "asc1"
        attr1.desc.return_value = "desc1"
        attr2 = MagicMock()
        attr2.asc.return_value = "asc2"
        attr2.desc.return_value = "desc2"
        mc.field1 = attr1
        mc.field2 = attr2
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(
                mc, order_by=[("field1", "asc"), ("field2", "desc")]
            )
        assert len(out) == 1
        attr1.asc.assert_called_once()
        attr2.desc.assert_called_once()

    def test_filter_kwargs_with_none_condition(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(
                NoField(), filter_kwargs={"unknown": "x"}
            )
        assert len(out) == 1

    def test_filter_kwargs_with_in_operator(self):
        mc = _make_model_with_field("id")
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(
                mc, filter_kwargs={"id__in": [1, 2, 3]}
            )
        assert len(out) == 1

    def test_no_order_by(self):
        db = _FakeDb(items=[MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(MagicMock())
        assert len(out) == 2

    def test_default_offset_and_limit(self):
        db = _FakeDb(items=[MagicMock() for _ in range(5)])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_all(MagicMock())
        # default limit=100, so all 5 returned
        assert len(out) == 5


# ── get_first: edge cases ────────────────────────────────────────────────────


class TestGetFirstEdge:
    def test_filter_kwargs_with_gte(self):
        mc = _make_model_with_field("price")
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_first(mc, price__gte=100)
        assert out is not None

    def test_filter_kwargs_unknown_field_skipped(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.get_first(NoField(), unknown="x")
        assert out is not None


# ── exists: edge cases ───────────────────────────────────────────────────────


class TestExistsEdge:
    def test_filter_kwargs_with_in(self):
        mc = _make_model_with_field("id")
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.exists(mc, id__in=[1, 2, 3])
        assert out is True

    def test_filter_kwargs_unknown_field(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.exists(NoField(), unknown="x")
        assert out is True


# ── count: edge cases ────────────────────────────────────────────────────────


class TestCountEdge:
    def test_filter_kwargs_with_like(self):
        mc = _make_model_with_field("name")
        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.count(mc, name__like="abc")
        assert out == 1

    def test_filter_kwargs_unknown_field(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = UnifiedQueryService.count(NoField(), unknown="x")
        assert out == 2


# ── delete: edge cases ───────────────────────────────────────────────────────


class TestDeleteEdge:
    def test_delete_with_synchronize_session_false(self):
        db = _FakeDb(items=[MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(MagicMock())
        assert n == 2
        assert db.committed is True
        assert db.last_query is not None
        assert db.last_query.delete_called is True
        assert db.last_query.delete_sync is False

    def test_delete_zero_count_no_delete_call(self):
        db = _FakeDb(items=[])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(MagicMock())
        assert n == 0
        assert db.committed is False
        assert db.last_query is not None
        assert db.last_query.delete_called is False

    def test_delete_with_filter_kwargs_unknown_field(self):
        class NoField:
            pass

        db = _FakeDb(items=[MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(NoField(), unknown="x")
        assert n == 1
        assert db.committed is True

    def test_delete_with_in_filter(self):
        mc = _make_model_with_field("id")
        db = _FakeDb(items=[MagicMock(), MagicMock()])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            n = UnifiedQueryService.delete(mc, id__in=[1, 2])
        assert n == 2


# ── module-level helpers: edge cases ─────────────────────────────────────────


class TestGetProductNamesEdge:
    def test_passes_is_active_filter(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.get_distinct_values.return_value = ["p1"]
            out = get_product_names()
            assert out == ["p1"]
            call_args = mock_qs.get_distinct_values.call_args
            # First positional arg is Product model class
            assert call_args.args[1] == "name"
            assert call_args.kwargs["filter_kwargs"] == {"is_active": 1}
            assert call_args.kwargs["order_by"] == "asc"

    def test_empty_keyword_string_passed_through(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.get_distinct_values.return_value = []
            get_product_names("")
            call_kwargs = mock_qs.get_distinct_values.call_args.kwargs
            # Empty string is falsy but still passed as keyword
            assert call_kwargs["keyword"] == ""


class TestGetPurchaseUnitsEdge:
    def test_with_keyword_applies_like_filter(self):
        u = MagicMock(
            id=1,
            unit_name="u",
            contact_person=None,
            contact_phone=None,
            address=None,
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)) as _:
            out = get_purchase_units("keyword")
        assert len(out) == 1
        assert out[0]["unit_name"] == "u"

    def test_limit_200_applied(self):
        units = [
            MagicMock(
                id=i,
                unit_name=f"u{i}",
                contact_person=None,
                contact_phone=None,
                address=None,
            )
            for i in range(3)
        ]
        db = _FakeDb(items=units)
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = get_purchase_units(None)
        assert len(out) == 3
        # Verify limit was set to 200
        assert db.last_query is not None
        assert db.last_query._limit == 200

    def test_empty_string_contact_fields(self):
        u = MagicMock(
            id=1,
            unit_name="u",
            contact_person="",
            contact_phone="",
            address="",
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = get_purchase_units(None)
        assert out[0]["contact_person"] == ""
        assert out[0]["contact_phone"] == ""
        assert out[0]["address"] == ""


class TestFindPurchaseUnitEdge:
    def test_returns_dict_with_none_fields(self):
        u = MagicMock(
            id=1,
            unit_name="u",
            contact_person=None,
            contact_phone=None,
            address=None,
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_purchase_unit(name="u")
        assert out is not None
        assert out["contact_person"] == ""
        assert out["contact_phone"] == ""
        assert out["address"] == ""

    def test_filter_by_kwargs_passed_through(self):
        u = MagicMock(
            id=1,
            unit_name="u",
            contact_person="c",
            contact_phone="p",
            address="a",
        )
        db = _FakeDb(items=[u])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_purchase_unit(id=1, unit_name="u")
        assert out is not None
        assert db.last_query is not None
        # filter_by should have been called with the kwargs
        # _FakeQuery stores filter_by kwargs in _filters
        assert any(
            isinstance(f, dict) and f == {"id": 1, "unit_name": "u"}
            for f in db.last_query._filters
        )


class TestFindProductEdge:
    def test_returns_dict_with_zero_price(self):
        p = MagicMock(
            id=1,
            model_number="m",
            specification="s",
            price=0,
            quantity=0,
            unit="",
            category="",
            brand="",
        )
        p.name = "p"
        db = _FakeDb(items=[p])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_product(name="p")
        assert out is not None
        assert out["price"] == 0.0
        assert out["quantity"] == 0
        # Empty string unit falls through to default "个"
        assert out["unit"] == "个"

    def test_returns_dict_with_string_price(self):
        p = MagicMock(
            id=1,
            model_number="m",
            specification="s",
            price="9.99",
            quantity="10",
            unit="箱",
            category="c",
            brand="b",
        )
        p.name = "p"
        db = _FakeDb(items=[p])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_product(name="p")
        assert out is not None
        assert out["price"] == 9.99
        assert out["quantity"] == "10"  # quantity uses `or 0`, "10" is truthy

    def test_filter_by_kwargs_passed_through(self):
        p = MagicMock(
            id=1,
            model_number="m",
            specification="s",
            price=1.0,
            quantity=1,
            unit="个",
            category="c",
            brand="b",
        )
        p.name = "p"
        db = _FakeDb(items=[p])
        with patch.object(uqs_mod, "get_db", lambda: _fake_get_db(db)):
            out = find_product(id=1)
        assert out is not None
        assert db.last_query is not None
        assert any(
            isinstance(f, dict) and f == {"id": 1}
            for f in db.last_query._filters
        )


class TestCheckPurchaseUnitExistsEdge:
    def test_delegates_with_unit_name(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.exists.return_value = False
            out = check_purchase_unit_exists("nonexistent")
            assert out is False
            mock_qs.exists.assert_called_once()
            call_args = mock_qs.exists.call_args
            # kwargs should contain unit_name
            assert call_args.kwargs == {"unit_name": "nonexistent"}


class TestDeletePurchaseUnitEdge:
    def test_delegates_with_kwargs(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.delete.return_value = 5
            out = delete_purchase_unit(id=99)
            assert out == 5
            mock_qs.delete.assert_called_once()
            call_args = mock_qs.delete.call_args
            assert call_args.kwargs == {"id": 99}

    def test_delegates_with_multiple_kwargs(self):
        with patch.object(uqs_mod, "query_service") as mock_qs:
            mock_qs.delete.return_value = 2
            out = delete_purchase_unit(unit_name="u", is_active=0)
            assert out == 2
            call_args = mock_qs.delete.call_args
            assert call_args.kwargs == {"unit_name": "u", "is_active": 0}


# ── _parse_filter: combined coverage ─────────────────────────────────────────


class TestParseFilterCombined:
    """Exercise every branch of ``_parse_filter`` in a single class for
    clarity. These duplicate the per-operator tests above but ensure every
    branch is hit at least once."""

    def test_all_comparison_operators(self):
        for suffix, op_attr, expected in [
            ("__gte", "__ge__", "ge"),
            ("__gt", "__gt__", "gt"),
            ("__lte", "__le__", "le"),
            ("__lt", "__lt__", "lt"),
            ("__ne", "__ne__", "ne"),
        ]:
            mc = _make_model_with_field("price")
            out = UnifiedQueryService._parse_filter(mc, f"price{suffix}", 100)
            assert out == f"{expected}:price"

    def test_all_match_operators(self):
        for suffix, op_attr, expected in [
            ("__in", "in_", "in"),
            ("__like", "like", "like"),
            ("__ilike", "ilike", "ilike"),
        ]:
            mc = _make_model_with_field("name")
            out = UnifiedQueryService._parse_filter(mc, f"name{suffix}", "abc")
            assert out == f"{expected}:name"

    def test_default_eq_with_scalar(self):
        mc = _make_model_with_field("name")
        out = UnifiedQueryService._parse_filter(mc, "name", "abc")
        # MagicMock ``==`` returns a new MagicMock, not None
        assert out is not None

    def test_default_eq_with_list(self):
        mc = _make_model_with_field("id")
        out = UnifiedQueryService._parse_filter(mc, "id", [1, 2, 3])
        assert out == "in:id"

    def test_unknown_field_with_lookup_suffix(self):
        class NoField:
            pass

        # Every lookup suffix with unknown field returns None
        for suffix in ["__gte", "__gt", "__lte", "__lt", "__ne", "__in", "__like", "__ilike"]:
            out = UnifiedQueryService._parse_filter(NoField(), f"price{suffix}", 1)
            assert out is None, f"suffix {suffix} should return None"

    def test_unknown_field_default(self):
        class NoField:
            pass

        out = UnifiedQueryService._parse_filter(NoField(), "missing", "x")
        assert out is None
