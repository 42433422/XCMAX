"""Tests for app.application.wechat_task_app_service — business logic without DB."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.application.wechat_task_app_service import (
    WechatTaskApplicationService,
    get_wechat_task_app_service,
)


@pytest.fixture
def service():
    return WechatTaskApplicationService()


def _mock_db_ctx(mock_db: MagicMock):
    """Return a context manager that yields mock_db, for patching get_db."""
    @contextmanager
    def _ctx():
        yield mock_db
    return _ctx


# ---------------------------------------------------------------------------
# _is_order_like_message
# ---------------------------------------------------------------------------


class TestIsOrderLikeMessage:
    def test_valid_order(self, service):
        text = "需要环氧地坪漆 规格 5桶"
        assert service._is_order_like_message(text) is True

    def test_too_short(self, service):
        assert service._is_order_like_message("abc") is False

    def test_empty(self, service):
        assert service._is_order_like_message("") is False

    def test_query_keyword(self, service):
        assert service._is_order_like_message("查询产品规格 5桶") is False

    def test_no_spec(self, service):
        assert service._is_order_like_message("需要5桶") is False

    def test_no_unit(self, service):
        assert service._is_order_like_message("需要环氧地坪漆 规格5") is False

    def test_kg_unit(self, service):
        assert service._is_order_like_message("环氧地坪漆 规格 50kg") is True

    def test_公斤_unit(self, service):
        assert service._is_order_like_message("环氧地坪漆 规格 50公斤") is True

    def test_查看_keyword(self, service):
        assert service._is_order_like_message("查看环氧地坪漆 规格 5桶") is False

    def test_哪些_keyword(self, service):
        assert service._is_order_like_message("哪些产品规格 5桶") is False

    def test_列表_keyword(self, service):
        assert service._is_order_like_message("列表产品规格 5桶") is False

    def test_none_input(self, service):
        assert service._is_order_like_message(None) is False


# ---------------------------------------------------------------------------
# _infer_task_type_from_text
# ---------------------------------------------------------------------------


class TestInferTaskTypeFromText:
    def test_order_like(self, service):
        assert service._infer_task_type_from_text("环氧地坪漆 规格 5桶") == "shipment_order"

    def test_not_order_like(self, service):
        assert service._infer_task_type_from_text("hello") == "unknown"


# ---------------------------------------------------------------------------
# recognize_order
# ---------------------------------------------------------------------------


class TestRecognizeOrder:
    def test_buy_pattern(self, service):
        result = service.recognize_order("买 5箱 环氧地坪漆")
        assert result is not None
        assert result["type"] == "order"
        assert result["quantity"] == 5
        assert result["unit"] == "箱"

    def test_need_pattern(self, service):
        result = service.recognize_order("需要 10个 产品A")
        assert result is not None
        assert result["quantity"] == 10

    def test_quantity_first(self, service):
        result = service.recognize_order("5箱 环氧地坪漆")
        assert result is not None
        assert result["quantity"] == 5

    def test_product_first(self, service):
        result = service.recognize_order("环氧地坪漆 5箱")
        assert result is not None
        assert result["quantity"] == 5

    def test_no_match(self, service):
        result = service.recognize_order("今天天气不错")
        assert result is None

    def test_empty(self, service):
        result = service.recognize_order("")
        assert result is None

    def test订购_pattern(self, service):
        result = service.recognize_order("订购 3盒 礼品")
        assert result is not None
        assert result["quantity"] == 3


# ---------------------------------------------------------------------------
# recognize_shipment
# ---------------------------------------------------------------------------


class TestRecognizeShipment:
    def test_发货_colon(self, service):
        result = service.recognize_shipment("发货：环氧地坪漆 5桶")
        assert result is not None
        assert result["type"] == "shipment"
        assert result["products"] is not None

    def test_已发货(self, service):
        result = service.recognize_shipment("已发货 环氧地坪漆 5桶")
        assert result is not None

    def test_发出(self, service):
        result = service.recognize_shipment("发出 环氧地坪漆 5桶")
        assert result is not None

    def test_安排发货(self, service):
        result = service.recognize_shipment("安排发货：环氧地坪漆 5桶")
        assert result is not None

    def test_no_match(self, service):
        result = service.recognize_shipment("今天天气不错")
        assert result is None

    def test_shipment_without_products(self, service):
        result = service.recognize_shipment("发货：一些东西")
        assert result is not None
        assert result["products"] is None


# ---------------------------------------------------------------------------
# _recognize_message_type
# ---------------------------------------------------------------------------


class TestRecognizeMessageType:
    def test_order(self, service):
        assert service._recognize_message_type("买 5箱 产品") == "order"

    def test_shipment(self, service):
        # Use text that matches shipment but NOT order (no quantity+unit after 发货)
        assert service._recognize_message_type("发货：明天安排") == "shipment"

    def test_unknown(self, service):
        assert service._recognize_message_type("hello") == "unknown"

    def test_order_takes_precedence(self, service):
        # "发货：产品 5箱" matches order pattern first (5箱), so returns "order"
        assert service._recognize_message_type("发货：产品 5箱") == "order"


# ---------------------------------------------------------------------------
# confirm_task / ignore_task
# ---------------------------------------------------------------------------


class TestConfirmTask:
    def test_not_exists(self, service):
        with patch.object(service, "_task_exists", return_value=False):
            result = service.confirm_task(999)
            assert result["success"] is False

    def test_success(self, service):
        with patch.object(service, "_task_exists", return_value=True), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.confirm_task(1)
            assert result["success"] is True

    def test_error(self, service):
        with patch.object(service, "_task_exists", side_effect=RuntimeError("db error")):
            result = service.confirm_task(1)
            assert result["success"] is False


class TestIgnoreTask:
    def test_not_exists(self, service):
        with patch.object(service, "_task_exists", return_value=False):
            result = service.ignore_task(999)
            assert result["success"] is False

    def test_success(self, service):
        with patch.object(service, "_task_exists", return_value=True), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.ignore_task(1)
            assert result["success"] is True


# ---------------------------------------------------------------------------
# process_message
# ---------------------------------------------------------------------------


class TestProcessMessage:
    def test_task_not_found(self, service):
        with patch.object(service, "_get_task", return_value=None):
            result = service.process_message(999)
            assert result["success"] is False

    def test_order_message(self, service):
        task = {"raw_text": "买 5箱 产品A"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True
            assert "order_info" in result

    def test_shipment_message(self, service):
        task = {"raw_text": "发货：明天安排"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True
            assert "shipment_info" in result

    def test_unknown_message(self, service):
        task = {"raw_text": "hello world"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True
            assert "待处理" in result["message"]

    def test_process_order_failure(self, service):
        task = {"raw_text": "买 5箱 产品A"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_process_order_message", return_value={"success": False, "message": "fail"}), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is False

    def test_error(self, service):
        with patch.object(service, "_get_task", side_effect=RuntimeError("db error")):
            result = service.process_message(1)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# _process_order_message
# ---------------------------------------------------------------------------


class TestProcessOrderMessage:
    def test_success(self, service):
        task = {"raw_text": "买 5箱 产品A"}
        result = service._process_order_message(task)
        assert result["success"] is True
        assert result["order_info"]["quantity"] == 5

    def test_no_order_info(self, service):
        task = {"raw_text": "hello"}
        result = service._process_order_message(task)
        assert result["success"] is False

    def test_error(self, service):
        task = MagicMock()
        task.get.side_effect = RuntimeError("fail")
        result = service._process_order_message(task)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _process_shipment_message
# ---------------------------------------------------------------------------


class TestProcessShipmentMessage:
    def test_success(self, service):
        task = {"raw_text": "发货：明天安排"}
        result = service._process_shipment_message(task)
        assert result["success"] is True

    def test_no_shipment_info(self, service):
        task = {"raw_text": "hello"}
        result = service._process_shipment_message(task)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _update_task_status
# ---------------------------------------------------------------------------


class TestUpdateTaskStatus:
    def test_invalid_status_returns_false(self, service):
        # ValueError is in RECOVERABLE_ERRORS, so it's caught and returns False
        result = service._update_task_status(1, "invalid")
        assert result is False

    def test_task_not_found(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._update_task_status(999, "pending")
            assert result is False

    def test_valid_statuses(self, service):
        for status in ("pending", "confirmed", "done", "ignored"):
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_task
            with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
                result = service._update_task_status(1, status)
                assert result is True


# ---------------------------------------------------------------------------
# get_tasks
# ---------------------------------------------------------------------------


class TestGetTasks:
    def test_success(self, service):
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.contact_id = None
        mock_task.username = "u"
        mock_task.display_name = "d"
        mock_task.message_id = "m"
        mock_task.msg_timestamp = 0
        mock_task.raw_text = "t"
        mock_task.task_type = "order"
        mock_task.status = "pending"
        mock_task.last_status_at = None
        mock_task.created_at = None
        mock_task.updated_at = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_task]
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service.get_tasks()
            assert len(result) == 1
            assert result[0]["id"] == 1

    def test_error(self, service):
        with patch("app.application.wechat_task_app_service.get_db", side_effect=RuntimeError("fail")):
            result = service.get_tasks()
            assert result == []


# ---------------------------------------------------------------------------
# get_contacts
# ---------------------------------------------------------------------------


class TestGetContacts:
    def test_success(self, service):
        mock_row = MagicMock()
        mock_row.username = "u"
        mock_row.display_name = "d"
        mock_row.contact_id = 1
        mock_row.last_message_time = 0
        mock_row.message_count = 5
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_row]
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service.get_contacts()
            assert len(result) == 1

    def test_with_keyword(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service.get_contacts(keyword="test")
            assert result == []

    def test_error(self, service):
        with patch("app.application.wechat_task_app_service.get_db", side_effect=RuntimeError("fail")):
            result = service.get_contacts()
            assert result == []


# ---------------------------------------------------------------------------
# scan_messages
# ---------------------------------------------------------------------------


class TestScanMessages:
    def test_no_db_path(self, service, monkeypatch):
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/nonexistent/path.db")
        result = service.scan_messages()
        assert result == []

    def test_import_error(self, service, monkeypatch):
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/nonexistent/path.db")
        with patch("app.utils.path_utils.get_resource_path", return_value="/tmp"):
            result = service.scan_messages()
            assert result == []

    def test_error(self, service, monkeypatch):
        with patch("app.utils.path_utils.get_resource_path", side_effect=RuntimeError("fail")):
            result = service.scan_messages()
            assert result == []


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task
# ---------------------------------------------------------------------------


class TestInsertOrIgnoreWechatTask:
    def test_empty_raw_text(self, service):
        result = service._insert_or_ignore_wechat_task(raw_text="")
        assert result is None

    def test_duplicate_message(self, service):
        mock_db = MagicMock()
        existing = MagicMock()
        existing.id = 42
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._insert_or_ignore_wechat_task(
                raw_text="test", message_id="msg1", username="u1"
            )
            assert result == 42

    def test_insert_success(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_task = MagicMock()
        mock_task.id = 1
        def mock_refresh(task):
            task.id = 1
        mock_db.refresh = mock_refresh
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._insert_or_ignore_wechat_task(raw_text="test message")
            assert result == 1

    def test_integrity_error(self, service):
        from sqlalchemy.exc import IntegrityError
        existing = MagicMock()
        existing.id = 99
        call_count = 0

        def get_db_ctx():
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.add.side_effect = IntegrityError("dup", None, None)
            m.query.return_value.filter.return_value.first.return_value = existing
            return _mock_db_ctx(m)()

        with patch("app.application.wechat_task_app_service.get_db", side_effect=get_db_ctx):
            result = service._insert_or_ignore_wechat_task(
                raw_text="test", message_id="m1", username="u1"
            )
            assert result == 99

    def test_recoverable_error(self, service):
        mock_db = MagicMock()
        mock_db.add.side_effect = OSError("disk full")
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._insert_or_ignore_wechat_task(raw_text="test")
            assert result is None


# ---------------------------------------------------------------------------
# _get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_found(self, service):
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.contact_id = None
        mock_task.username = "u"
        mock_task.display_name = "d"
        mock_task.message_id = "m"
        mock_task.msg_timestamp = 0
        mock_task.raw_text = "t"
        mock_task.task_type = "order"
        mock_task.status = "pending"
        mock_task.last_status_at = None
        mock_task.created_at = None
        mock_task.updated_at = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._get_task(1)
            assert result is not None
            assert result["id"] == 1

    def test_not_found(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            result = service._get_task(999)
            assert result is None

    def test_error(self, service):
        with patch("app.application.wechat_task_app_service.get_db", side_effect=RuntimeError("fail")):
            result = service._get_task(1)
            assert result is None


# ---------------------------------------------------------------------------
# _task_exists
# ---------------------------------------------------------------------------


class TestTaskExists:
    def test_exists(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            assert service._task_exists(1) is True

    def test_not_exists(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.wechat_task_app_service.get_db", side_effect=_mock_db_ctx(mock_db)):
            assert service._task_exists(999) is False

    def test_error(self, service):
        with patch("app.application.wechat_task_app_service.get_db", side_effect=RuntimeError("fail")):
            assert service._task_exists(1) is False


# ---------------------------------------------------------------------------
# get_wechat_task_app_service singleton
# ---------------------------------------------------------------------------


class TestGetWechatTaskAppService:
    def test_singleton(self):
        import app.application.wechat_task_app_service as mod
        old = mod._wechat_task_app_service
        mod._wechat_task_app_service = None
        try:
            svc1 = get_wechat_task_app_service()
            svc2 = get_wechat_task_app_service()
            assert svc1 is svc2
        finally:
            mod._wechat_task_app_service = old
