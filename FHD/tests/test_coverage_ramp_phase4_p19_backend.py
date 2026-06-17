"""COVERAGE_RAMP Phase 4 round 19: customer_app_service CRUD + match (30.6%→)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.customer_app_service import CustomerApplicationService


def _fluent(*, first=None, all_=None, count_=0) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.first.return_value = first
    q.all.return_value = list(all_ or [])
    q.count.return_value = count_
    return q


def _session(queries=None) -> MagicMock:
    s = MagicMock()
    if queries is not None:
        s.query.side_effect = list(queries)
    return s


def _unit(**kw) -> SimpleNamespace:
    base = {
        "id": 1,
        "unit_name": "七彩乐园",
        "contact_person": "张三",
        "contact_phone": "13800000000",
        "address": "北京",
        "discount_rate": 1.0,
        "is_active": True,
        "created_at": datetime(2024, 1, 1),
        "updated_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def svc() -> CustomerApplicationService:
    return CustomerApplicationService()


def _bind(svc, session):
    return patch.object(svc, "_get_session", return_value=session)


# ---------------------------------------------------------------------------
# get_all / get_by_id
# ---------------------------------------------------------------------------


def test_get_all_with_keyword(svc) -> None:
    s = _session([_fluent(all_=[_unit()], count_=1)])
    with _bind(svc, s):
        out = svc.get_all(keyword="七彩", page=1, per_page=10)
    assert out["success"] is True
    assert out["total"] == 1
    assert out["data"][0]["customer_name"] == "七彩乐园"
    s.close.assert_called_once()


def test_get_all_error(svc) -> None:
    s = MagicMock()
    s.query.side_effect = RuntimeError("db down")
    with _bind(svc, s):
        out = svc.get_all()
    assert out["success"] is False
    assert out["total"] == 0


def test_get_by_id_found(svc) -> None:
    s = _session([_fluent(first=_unit())])
    with _bind(svc, s):
        out = svc.get_by_id(1)
    assert out["success"] is True
    assert out["data"]["id"] == 1


def test_get_by_id_missing(svc) -> None:
    s = _session([_fluent(first=None)])
    with _bind(svc, s):
        out = svc.get_by_id(99)
    assert out["success"] is False


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_empty_name(svc) -> None:
    s = _session([])
    with _bind(svc, s):
        out = svc.create({})
    assert out["success"] is False
    assert "不能为空" in out["message"]


def test_create_duplicate(svc) -> None:
    s = _session([_fluent(first=_unit())])
    with _bind(svc, s):
        out = svc.create({"customer_name": "七彩乐园"})
    assert out["success"] is False
    assert "已存在" in out["message"]


def test_create_success(svc) -> None:
    s = _session([_fluent(first=None)])
    with _bind(svc, s):
        out = svc.create({"customer_name": "新客户", "contact_person": "李四"})
    assert out["success"] is True
    s.add.assert_called_once()
    s.commit.assert_called_once()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_not_found(svc) -> None:
    s = _session([_fluent(first=None)])
    with _bind(svc, s):
        out = svc.update(1, {"contact_person": "新"})
    assert out["success"] is False


def test_update_success_no_rename(svc) -> None:
    s = _session([_fluent(first=_unit())])
    with _bind(svc, s):
        out = svc.update(
            1, {"contact_person": "新人", "contact_phone": "111", "contact_address": "上海"}
        )
    assert out["success"] is True


def test_update_rename_conflict(svc) -> None:
    s = _session([_fluent(first=_unit()), _fluent(first=_unit(id=2))])
    with _bind(svc, s):
        out = svc.update(1, {"customer_name": "占用名"})
    assert out["success"] is False
    assert "已存在" in out["message"]


def test_update_rename_ok(svc) -> None:
    s = _session([_fluent(first=_unit()), _fluent(first=None)])
    with _bind(svc, s):
        out = svc.update(1, {"customer_name": "新名字"})
    assert out["success"] is True
    assert out["data"]["customer_name"] == "新名字"


# ---------------------------------------------------------------------------
# _check_shipment_associations
# ---------------------------------------------------------------------------


@contextmanager
def _fake_db(session):
    yield session


def test_check_shipment_associations(svc) -> None:
    rec = SimpleNamespace(
        id=1, product_name="苹果", quantity_kg=10, created_at=datetime(2024, 1, 1)
    )
    db = MagicMock()
    db.query.side_effect = [_fluent(all_=[rec]), _fluent(count_=1)]
    with patch("app.db.session.get_db", lambda: _fake_db(db)):
        out = svc._check_shipment_associations("七彩")
    assert out["has_associations"] is True
    assert out["shipment_count"] == 1
    assert out["sample_records"][0]["product_name"] == "苹果"


def test_check_shipment_associations_error(svc) -> None:
    db = MagicMock()
    db.query.side_effect = RuntimeError("oops")
    with patch("app.db.session.get_db", lambda: _fake_db(db)):
        out = svc._check_shipment_associations("七彩")
    assert out["has_associations"] is False


# ---------------------------------------------------------------------------
# delete / batch_delete
# ---------------------------------------------------------------------------


def test_delete_not_found(svc) -> None:
    s = _session([_fluent(first=None)])
    with _bind(svc, s):
        out = svc.delete(1)
    assert out["success"] is False
    assert out["deleted_count"] == 0


def test_delete_blocked_by_associations(svc) -> None:
    s = _session([_fluent(first=_unit())])
    check = {"has_associations": True, "shipment_count": 2, "sample_records": []}
    with _bind(svc, s), patch.object(svc, "_check_shipment_associations", return_value=check):
        out = svc.delete(1, force=False)
    assert out["success"] is False
    assert out["has_associations"] is True


def test_delete_success_force(svc) -> None:
    s = _session([_fluent(first=_unit())])
    check = {"has_associations": True, "shipment_count": 2, "sample_records": []}
    with _bind(svc, s), patch.object(svc, "_check_shipment_associations", return_value=check):
        out = svc.delete(1, force=True)
    assert out["success"] is True
    assert out["deleted_count"] == 1
    s.delete.assert_called_once()


def test_batch_delete_none_found(svc) -> None:
    s = _session([_fluent(all_=[])])
    with _bind(svc, s):
        out = svc.batch_delete([1, 2])
    assert out["success"] is False


def test_batch_delete_blocked(svc) -> None:
    s = _session([_fluent(all_=[_unit(), _unit(id=2, unit_name="第二")])])
    check = {"has_associations": True, "shipment_count": 1, "sample_records": []}
    with _bind(svc, s), patch.object(svc, "_check_shipment_associations", return_value=check):
        out = svc.batch_delete([1, 2], force=False)
    assert out["success"] is False
    assert out["has_associations"] is True


def test_batch_delete_success(svc) -> None:
    s = _session([_fluent(all_=[_unit(), _unit(id=2, unit_name="第二")])])
    with (
        _bind(svc, s),
        patch.object(svc, "_check_shipment_associations", return_value={"has_associations": False}),
    ):
        out = svc.batch_delete([1, 2], force=False)
    assert out["success"] is True
    assert out["deleted_count"] == 2
    assert s.delete.call_count == 2


# ---------------------------------------------------------------------------
# get_purchase_unit_by_name / match_purchase_unit
# ---------------------------------------------------------------------------


def test_get_purchase_unit_by_name_found(svc) -> None:
    s = _session([_fluent(first=_unit())])
    with _bind(svc, s):
        out = svc.get_purchase_unit_by_name("七彩乐园")
    assert out is not None
    assert out.unit_name == "七彩乐园"


def test_get_purchase_unit_by_name_none(svc) -> None:
    s = _session([_fluent(first=None)])
    with _bind(svc, s):
        assert svc.get_purchase_unit_by_name("无") is None


def test_match_purchase_unit_empty(svc) -> None:
    assert svc.match_purchase_unit("  ") is None


def test_match_purchase_unit_exact(svc) -> None:
    s = _session([_fluent(first=_unit())])
    with _bind(svc, s):
        out = svc.match_purchase_unit("七彩乐园")
    assert out is not None
    assert out.unit_name == "七彩乐园"


def test_match_purchase_unit_substring(svc) -> None:
    s = _session([_fluent(first=None), _fluent(all_=[_unit()])])
    with _bind(svc, s):
        out = svc.match_purchase_unit("七彩")
    assert out is not None
    assert out.unit_name == "七彩乐园"


def test_match_purchase_unit_no_match(svc) -> None:
    s = _session([_fluent(first=None), _fluent(all_=[])])
    with _bind(svc, s):
        assert svc.match_purchase_unit("完全不同") is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
