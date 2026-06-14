"""COVERAGE_RAMP Phase 4 round 13: purchase_service read/update paths (12%→).

Uses a fluent self-returning query mock injected through a fake get_db
context manager so no real DB is required.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import PurchaseOrder, Supplier
from app.services.purchase_service import PurchaseService


def _fluent(*, all_=None, first=None, count=0) -> MagicMock:
    """A query mock whose chain methods return self."""
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "options"):
        getattr(q, attr).return_value = q
    q.all.return_value = list(all_ or [])
    q.first.return_value = first
    q.count.return_value = count
    return q


@contextmanager
def _fake_db(session):
    yield session


def _patched_db(session):
    return patch("app.services.purchase_service.get_db", lambda: _fake_db(session))


@pytest.fixture
def svc() -> PurchaseService:
    return PurchaseService()


# ---------------------------------------------------------------------------
# static helpers
# ---------------------------------------------------------------------------


def test_decimal_to_float() -> None:
    assert PurchaseService._decimal_to_float(Decimal("1.50")) == 1.5
    assert PurchaseService._decimal_to_float("x") == "x"
    assert PurchaseService._decimal_to_float(None) is None


def test_model_to_dict_none() -> None:
    assert PurchaseService._model_to_dict(None) == {}


def test_model_to_dict_real_model() -> None:
    s = Supplier(code="C1", name="供应商A")
    d = PurchaseService._model_to_dict(s)
    assert d["code"] == "C1"
    assert d["name"] == "供应商A"


# ---------------------------------------------------------------------------
# suppliers
# ---------------------------------------------------------------------------


def test_get_suppliers_empty(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(all_=[])
    with _patched_db(session):
        out = svc.get_suppliers()
    assert out["success"] is True
    assert out["count"] == 0


def test_get_suppliers_with_filters(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(all_=[Supplier(code="C1", name="A")])
    with _patched_db(session):
        out = svc.get_suppliers(status="active", keyword="A")
    assert out["count"] == 1
    assert out["data"][0]["code"] == "C1"


def test_get_supplier_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=Supplier(code="C9", name="找到了"))
    with _patched_db(session):
        out = svc.get_supplier(9)
    assert out["success"] is True
    assert out["data"]["name"] == "找到了"


def test_get_supplier_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.get_supplier(404)
    assert out["success"] is False
    assert "不存在" in out["message"]


def test_update_supplier_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.update_supplier(1, {"name": "x"})
    assert out["success"] is False


def test_update_supplier_success(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=Supplier(code="C1", name="旧名"))
    with _patched_db(session):
        out = svc.update_supplier(1, {"name": "新名", "contact_person": "张三"})
    assert out["success"] is True
    assert out["data"]["name"] == "新名"


def test_delete_supplier_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.delete_supplier(1)
    assert out["success"] is False


def test_delete_supplier_success(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=Supplier(code="C1", name="A"))
    with _patched_db(session):
        out = svc.delete_supplier(1)
    assert out["success"] is True
    assert "已删除" in out["message"]


# ---------------------------------------------------------------------------
# purchase orders (read / guard branches)
# ---------------------------------------------------------------------------


def test_get_purchase_orders_empty(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(all_=[], count=0)
    with _patched_db(session):
        out = svc.get_purchase_orders()
    assert out["success"] is True
    assert out["total"] == 0
    assert out["data"] == []


def test_get_purchase_order_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.get_purchase_order(1)
    assert out["success"] is False


def test_update_purchase_order_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.update_purchase_order(1, {})
    assert out["success"] is False


def test_update_purchase_order_not_draft(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=PurchaseOrder(status="approved"))
    with _patched_db(session):
        out = svc.update_purchase_order(1, {})
    assert out["success"] is False
    assert "草稿" in out["message"]


def test_approve_purchase_order_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.approve_purchase_order(1, "approver")
    assert out["success"] is False


def test_cancel_purchase_order_not_found(svc: PurchaseService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.cancel_purchase_order(1)
    assert out["success"] is False
