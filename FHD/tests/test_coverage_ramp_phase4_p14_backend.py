"""COVERAGE_RAMP Phase 4 round 14: wechat_task_service recognizers + DB-mock paths (10%→)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import WechatTask
from app.services.wechat_task_service import WechatTaskService


def _fluent(*, all_=None, first=None) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.all.return_value = list(all_ or [])
    q.first.return_value = first
    return q


@contextmanager
def _fake_db(session):
    yield session


def _patched_db(session):
    return patch("app.services.wechat_task_service.get_db", lambda: _fake_db(session))


@pytest.fixture
def svc() -> WechatTaskService:
    return WechatTaskService()


# ---------------------------------------------------------------------------
# pure recognizers
# ---------------------------------------------------------------------------


def test_recognize_order_match(svc: WechatTaskService) -> None:
    out = svc.recognize_order("10箱 苹果")
    assert out is not None
    assert out["type"] == "order"
    assert out["quantity"] == 10
    assert out["product"] == "苹果"


def test_recognize_order_with_prefix(svc: WechatTaskService) -> None:
    out = svc.recognize_order("买 10 箱 苹果")
    assert out is not None
    assert out["quantity"] == 10


def test_recognize_order_no_match(svc: WechatTaskService) -> None:
    assert svc.recognize_order("普通对话内容") is None


def test_recognize_shipment_match(svc: WechatTaskService) -> None:
    out = svc.recognize_shipment("已发货 货物")
    assert out is not None
    assert out["type"] == "shipment"
    assert out["content"] == "货物"


def test_recognize_shipment_no_match(svc: WechatTaskService) -> None:
    assert svc.recognize_shipment("普通") is None


def test_is_order_like_message(svc: WechatTaskService) -> None:
    assert svc._is_order_like_message("规格28的货5桶") is True
    assert svc._is_order_like_message("查询规格") is False
    assert svc._is_order_like_message("短") is False
    assert svc._is_order_like_message("买5桶东西") is False  # no 规格 keyword


def test_infer_task_type(svc: WechatTaskService) -> None:
    assert svc._infer_task_type_from_text("规格28的货5桶") == "shipment_order"
    assert svc._infer_task_type_from_text("你好") == "unknown"


def test_recognize_message_type(svc: WechatTaskService) -> None:
    assert svc._recognize_message_type("买 10 箱 货") == "order"
    assert svc._recognize_message_type("已发货 货物") == "shipment"
    assert svc._recognize_message_type("随便聊聊") == "unknown"


# ---------------------------------------------------------------------------
# process_order / shipment message helpers
# ---------------------------------------------------------------------------


def test_process_order_message_success(svc: WechatTaskService) -> None:
    out = svc._process_order_message({"raw_text": "买 10 箱 货"})
    assert out["success"] is True
    assert out["order_info"]["quantity"] == 10


def test_process_order_message_unparseable(svc: WechatTaskService) -> None:
    out = svc._process_order_message({"raw_text": "无法解析"})
    assert out["success"] is False


def test_process_shipment_message_success(svc: WechatTaskService) -> None:
    out = svc._process_shipment_message({"raw_text": "已发货 货物"})
    assert out["success"] is True


# ---------------------------------------------------------------------------
# DB-mock paths
# ---------------------------------------------------------------------------


def test_task_exists_true_false(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=(1,))
    with _patched_db(session):
        assert svc._task_exists(1) is True
    session2 = MagicMock()
    session2.query.return_value = _fluent(first=None)
    with _patched_db(session2):
        assert svc._task_exists(2) is False


def test_update_task_status_invalid(svc: WechatTaskService) -> None:
    # invalid status raises ValueError internally -> caught -> returns False
    session = MagicMock()
    session.query.return_value = _fluent(first=WechatTask(id=1))
    with _patched_db(session):
        assert svc._update_task_status(1, "bogus") is False


def test_update_task_status_success(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=WechatTask(id=1))
    with _patched_db(session):
        assert svc._update_task_status(1, "done") is True


def test_confirm_task_not_found(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.confirm_task(99)
    assert out["success"] is False


def test_confirm_task_success(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=WechatTask(id=1))
    with _patched_db(session):
        out = svc.confirm_task(1)
    assert out["success"] is True
    assert "已确认" in out["message"]


def test_ignore_task_success(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=WechatTask(id=1))
    with _patched_db(session):
        out = svc.ignore_task(1)
    assert out["success"] is True
    assert "已忽略" in out["message"]


def test_get_task_found_and_missing(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=WechatTask(id=5, raw_text="hi", status="pending"))
    with _patched_db(session):
        out = svc._get_task(5)
    assert out is not None
    assert out["id"] == 5
    session2 = MagicMock()
    session2.query.return_value = _fluent(first=None)
    with _patched_db(session2):
        assert svc._get_task(6) is None


def test_get_tasks_empty(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(all_=[])
    with _patched_db(session):
        out = svc.get_tasks(contact_id=1, status="pending")
    assert out == []


def test_get_contacts_empty(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(all_=[])
    with _patched_db(session):
        out = svc.get_contacts(keyword="abc")
    assert out == []


def test_process_message_not_found(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(first=None)
    with _patched_db(session):
        out = svc.process_message(1)
    assert out["success"] is False
    assert "不存在" in out["message"]


def test_process_message_order_flow(svc: WechatTaskService) -> None:
    session = MagicMock()
    session.query.return_value = _fluent(
        first=WechatTask(id=1, raw_text="买 10 箱 货", status="pending")
    )
    with _patched_db(session):
        out = svc.process_message(1)
    assert out["success"] is True
