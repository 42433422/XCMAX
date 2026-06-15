"""COVERAGE_RAMP Phase 4 round 22: wechat_task_app_service (13.3%→)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.application import wechat_task_app_service as mod
from app.application.wechat_task_app_service import WechatTaskApplicationService
from app.db.models import WechatTask


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


def _patch_db(session):
    return patch.object(mod, "get_db", lambda: _fake_db(session))


def _patch_db_sequence(sessions):
    it = iter(sessions)
    return patch.object(mod, "get_db", lambda: _fake_db(next(it)))


@pytest.fixture
def svc() -> WechatTaskApplicationService:
    return WechatTaskApplicationService()


# ---------------------------------------------------------------------------
# pure recognizers (same logic family)
# ---------------------------------------------------------------------------


def test_recognize_order_and_shipment(svc) -> None:
    assert svc.recognize_order("买 10 箱 货")["quantity"] == 10
    assert svc.recognize_order("普通对话") is None
    assert svc.recognize_shipment("已发货 货物")["type"] == "shipment"
    assert svc.recognize_shipment("普通") is None


def test_is_order_like_and_infer(svc) -> None:
    assert svc._is_order_like_message("规格28的货5桶") is True
    assert svc._is_order_like_message("查询规格5桶") is False
    assert svc._is_order_like_message("短") is False
    assert svc._infer_task_type_from_text("规格28的货5桶") == "shipment_order"
    assert svc._infer_task_type_from_text("你好") == "unknown"


def test_recognize_message_type(svc) -> None:
    assert svc._recognize_message_type("买 10 箱 货") == "order"
    assert svc._recognize_message_type("已发货 货物") == "shipment"
    assert svc._recognize_message_type("闲聊") == "unknown"


def test_process_order_and_shipment_helpers(svc) -> None:
    assert svc._process_order_message({"raw_text": "买 10 箱 货"})["success"] is True
    assert svc._process_order_message({"raw_text": "无法解析"})["success"] is False
    assert svc._process_shipment_message({"raw_text": "已发货 货物"})["success"] is True
    assert svc._process_shipment_message({"raw_text": "无"})["success"] is False


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task
# ---------------------------------------------------------------------------


def test_insert_or_ignore_no_text(svc) -> None:
    assert svc._insert_or_ignore_wechat_task(raw_text="") is None


def test_insert_or_ignore_existing(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=WechatTask(id=5))
    with _patch_db(s):
        out = svc._insert_or_ignore_wechat_task(
            raw_text="hi", message_id="m1", username="u1"
        )
    assert out == 5


def test_insert_or_ignore_new(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        out = svc._insert_or_ignore_wechat_task(raw_text="hi")
    # new task's id is None on mocked refresh; insert path executed without error
    assert out is None
    s.add.assert_called_once()


def test_insert_or_ignore_integrity_error_recovers(svc) -> None:
    s1 = MagicMock()
    s1.query.return_value = _fluent(first=None)
    s1.commit.side_effect = IntegrityError("dup", None, Exception("x"))
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=WechatTask(id=7))
    with _patch_db_sequence([s1, s2]):
        out = svc._insert_or_ignore_wechat_task(
            raw_text="hi", message_id="m1", username="u1"
        )
    assert out == 7


# ---------------------------------------------------------------------------
# scan_messages (db missing -> [])
# ---------------------------------------------------------------------------


def test_scan_messages_db_missing(svc, monkeypatch) -> None:
    monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/nonexistent/dir/message_0.db")
    assert svc.scan_messages() == []


# ---------------------------------------------------------------------------
# DB-mock task lifecycle
# ---------------------------------------------------------------------------


def test_task_exists(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=(1,))
    with _patch_db(s):
        assert svc._task_exists(1) is True
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=None)
    with _patch_db(s2):
        assert svc._task_exists(2) is False


def test_update_task_status(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=WechatTask(id=1))
    with _patch_db(s):
        assert svc._update_task_status(1, "done") is True
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=WechatTask(id=1))
    with _patch_db(s2):
        assert svc._update_task_status(1, "bogus") is False


def test_confirm_and_ignore(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=WechatTask(id=1))
    with _patch_db(s):
        assert svc.confirm_task(1)["success"] is True
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=WechatTask(id=1))
    with _patch_db(s2):
        assert svc.ignore_task(1)["success"] is True
    s3 = MagicMock()
    s3.query.return_value = _fluent(first=None)
    with _patch_db(s3):
        assert svc.confirm_task(9)["success"] is False


def test_get_task_found_missing(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=WechatTask(id=5, raw_text="hi"))
    with _patch_db(s):
        assert svc._get_task(5)["id"] == 5
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=None)
    with _patch_db(s2):
        assert svc._get_task(6) is None


def test_get_tasks_and_contacts_empty(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(all_=[])
    with _patch_db(s):
        assert svc.get_tasks(contact_id=1, status="pending") == []
    s2 = MagicMock()
    s2.query.return_value = _fluent(all_=[])
    with _patch_db(s2):
        assert svc.get_contacts(keyword="abc") == []


def test_get_contacts_with_rows(svc) -> None:
    row = SimpleNamespace(
        username="u1",
        display_name="昵称",
        contact_id=3,
        last_message_time=123,
        message_count=2,
    )
    s = MagicMock()
    s.query.return_value = _fluent(all_=[row])
    with _patch_db(s):
        out = svc.get_contacts()
    assert out[0]["username"] == "u1"
    assert out[0]["message_count"] == 2


def test_process_message_flows(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        assert svc.process_message(1)["success"] is False
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=WechatTask(id=1, raw_text="买 10 箱 货"))
    with _patch_db(s2):
        assert svc.process_message(1)["success"] is True


def test_accessor_singleton() -> None:
    a = mod.get_wechat_task_app_service()
    b = mod.get_wechat_task_app_service()
    assert a is b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
