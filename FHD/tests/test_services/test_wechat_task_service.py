"""app/services/wechat_task_service WechatTaskService 测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.wechat_task_service import WechatTaskService


@pytest.fixture
def service():
    return WechatTaskService()


# ---------------------------------------------------------------------------
# _is_order_like_message
# ---------------------------------------------------------------------------


class TestIsOrderLikeMessage:
    def test_short_text_returns_false(self, service):
        assert service._is_order_like_message("ab") is False

    def test_empty_returns_false(self, service):
        assert service._is_order_like_message("") is False

    def test_query_keywords_returns_false(self, service):
        assert service._is_order_like_message("查询规格10桶") is False
        assert service._is_order_like_message("查看规格5公斤") is False
        assert service._is_order_like_message("哪些规格3桶") is False
        assert service._is_order_like_message("列表规格2kg") is False

    def test_no_spec_returns_false(self, service):
        assert service._is_order_like_message("我要买10桶苹果") is False

    def test_no_unit_returns_false(self, service):
        assert service._is_order_like_message("规格A产品") is False

    def test_valid_order_like(self, service):
        assert service._is_order_like_message("规格10桶产品A") is True
        assert service._is_order_like_message("规格5公斤产品B") is True
        assert service._is_order_like_message("规格3kg产品C") is True

    def test_case_insensitive_kg(self, service):
        assert service._is_order_like_message("规格10KG产品") is True
        assert service._is_order_like_message("规格10Kg产品") is True


# ---------------------------------------------------------------------------
# _infer_task_type_from_text
# ---------------------------------------------------------------------------


class TestInferTaskType:
    def test_order_like_returns_shipment_order(self, service):
        assert service._infer_task_type_from_text("规格10桶产品") == "shipment_order"

    def test_not_order_like_returns_unknown(self, service):
        assert service._infer_task_type_from_text("普通消息") == "unknown"


# ---------------------------------------------------------------------------
# recognize_order
# ---------------------------------------------------------------------------


class TestRecognizeOrder:
    def test_valid_order_pattern1(self, service):
        # Pattern requires space after unit char (e.g., "箱 " not "箱")
        result = service.recognize_order("10 箱 苹果")
        assert result is not None
        assert result["type"] == "order"
        assert result["quantity"] == 10
        assert result["unit"] == "箱 "

    def test_valid_order_pattern2(self, service):
        result = service.recognize_order("苹果 10 箱 ")
        assert result is not None
        assert result["type"] == "order"
        assert result["product"] == "苹果"

    def test_no_match_returns_none(self, service):
        assert service.recognize_order("普通消息") is None

    def test_empty_returns_none(self, service):
        assert service.recognize_order("") is None

    def test_raw_text_preserved(self, service):
        text = "10 箱 苹果"
        result = service.recognize_order(text)
        assert result["raw_text"] == text


# ---------------------------------------------------------------------------
# recognize_shipment
# ---------------------------------------------------------------------------


class TestRecognizeShipment:
    def test_shipment_with_colon(self, service):
        # Pattern requires space before colon: "发货 ：" not "发货："
        result = service.recognize_shipment("发货 ：10 箱 苹果")
        assert result is not None
        assert result["type"] == "shipment"

    def test_shipment_already_shipped(self, service):
        result = service.recognize_shipment("已发货 10 箱 苹果")
        assert result is not None
        assert result["type"] == "shipment"

    def test_shipment_sent_out(self, service):
        result = service.recognize_shipment("发出 5 桶 牛奶")
        assert result is not None
        assert result["type"] == "shipment"

    def test_arrange_shipment(self, service):
        result = service.recognize_shipment("安排发货 ：苹果 10 箱 ")
        assert result is not None
        assert result["type"] == "shipment"

    def test_no_match_returns_none(self, service):
        assert service.recognize_shipment("普通消息") is None

    def test_raw_text_preserved(self, service):
        text = "发货 ：10 箱 苹果"
        result = service.recognize_shipment(text)
        assert result["raw_text"] == text


# ---------------------------------------------------------------------------
# _recognize_message_type
# ---------------------------------------------------------------------------


class TestRecognizeMessageType:
    def test_order_type(self, service):
        assert service._recognize_message_type("10 箱 苹果") == "order"

    def test_shipment_type(self, service):
        # "发货 ：苹果已发出" matches shipment pattern but NOT order pattern
        assert service._recognize_message_type("发货 ：苹果已发出") == "shipment"

    def test_unknown_type(self, service):
        assert service._recognize_message_type("普通消息") == "unknown"


# ---------------------------------------------------------------------------
# process_message
# ---------------------------------------------------------------------------


class TestProcessMessage:
    def test_task_not_found(self, service):
        with patch.object(service, "_get_task", return_value=None):
            result = service.process_message(999)
            assert result["success"] is False
            assert "不存在" in result["message"]

    def test_order_message(self, service):
        task = {"raw_text": "10 箱 苹果"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True

    def test_shipment_message(self, service):
        task = {"raw_text": "发货 ：10 箱 苹果"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True

    def test_unknown_message_type(self, service):
        task = {"raw_text": "普通消息"}
        with patch.object(service, "_get_task", return_value=task), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.process_message(1)
            assert result["success"] is True
            assert "未知" in result["message"]

    def test_exception_returns_failure(self, service):
        with patch.object(service, "_get_task", side_effect=RuntimeError("db error")):
            result = service.process_message(1)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# confirm_task / ignore_task
# ---------------------------------------------------------------------------


class TestConfirmIgnoreTask:
    def test_confirm_task_not_exists(self, service):
        with patch.object(service, "_task_exists", return_value=False):
            result = service.confirm_task(999)
            assert result["success"] is False

    def test_confirm_task_success(self, service):
        with patch.object(service, "_task_exists", return_value=True), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.confirm_task(1)
            assert result["success"] is True

    def test_ignore_task_not_exists(self, service):
        with patch.object(service, "_task_exists", return_value=False):
            result = service.ignore_task(999)
            assert result["success"] is False

    def test_ignore_task_success(self, service):
        with patch.object(service, "_task_exists", return_value=True), \
             patch.object(service, "_update_task_status", return_value=True):
            result = service.ignore_task(1)
            assert result["success"] is True

    def test_confirm_task_exception(self, service):
        with patch.object(service, "_task_exists", side_effect=RuntimeError("err")):
            result = service.confirm_task(1)
            assert result["success"] is False

    def test_ignore_task_exception(self, service):
        with patch.object(service, "_task_exists", side_effect=RuntimeError("err")):
            result = service.ignore_task(1)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# _update_task_status
# ---------------------------------------------------------------------------


class TestUpdateTaskStatus:
    def test_invalid_status_returns_false(self, service):
        # ValueError is caught by RECOVERABLE_ERRORS, so it returns False
        result = service._update_task_status(1, "invalid_status")
        assert result is False

    def test_valid_statuses(self, service):
        for status in ("pending", "confirmed", "done", "ignored"):
            with patch("app.services.wechat_task_service.get_db") as mock_get_db:
                mock_db = MagicMock()
                mock_task = MagicMock()
                mock_db.query.return_value.filter.return_value.first.return_value = mock_task
                mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
                result = service._update_task_status(1, status)
                assert result is True

    def test_task_not_found(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._update_task_status(999, "done")
            assert result is False

    def test_db_error_returns_false(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("db err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._update_task_status(1, "done")
            assert result is False


# ---------------------------------------------------------------------------
# _get_task / _task_exists
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_task_found(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.id = 1
            mock_task.raw_text = "test"
            mock_task.status = "pending"
            mock_task.contact_id = None
            mock_task.username = "u"
            mock_task.display_name = "d"
            mock_task.message_id = "m"
            mock_task.msg_timestamp = 0
            mock_task.task_type = "unknown"
            mock_task.last_status_at = None
            mock_task.created_at = None
            mock_task.updated_at = None
            mock_db.query.return_value.filter.return_value.first.return_value = mock_task
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._get_task(1)
            assert result is not None
            assert result["id"] == 1

    def test_task_not_found(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._get_task(999)
            assert result is None

    def test_db_error_returns_none(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._get_task(1)
            assert result is None


class TestTaskExists:
    def test_exists(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            assert service._task_exists(1) is True

    def test_not_exists(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            assert service._task_exists(999) is False

    def test_db_error_returns_false(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            assert service._task_exists(1) is False


# ---------------------------------------------------------------------------
# get_tasks
# ---------------------------------------------------------------------------


class TestGetTasks:
    def test_returns_tasks(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_task = MagicMock()
            mock_task.id = 1
            mock_task.contact_id = None
            mock_task.username = "u"
            mock_task.display_name = "d"
            mock_task.message_id = "m"
            mock_task.msg_timestamp = 0
            mock_task.raw_text = "text"
            mock_task.task_type = "unknown"
            mock_task.status = "pending"
            mock_task.last_status_at = None
            mock_task.created_at = None
            mock_task.updated_at = None
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_task]
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service.get_tasks()
            assert len(result) == 1
            assert result[0]["id"] == 1

    def test_db_error_returns_empty(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service.get_tasks()
            assert result == []


# ---------------------------------------------------------------------------
# get_contacts
# ---------------------------------------------------------------------------


class TestGetContacts:
    def test_returns_contacts(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_row = MagicMock()
            mock_row.username = "user1"
            mock_row.display_name = "User One"
            mock_row.contact_id = 1
            mock_row.last_message_time = 1700000000
            mock_row.message_count = 5
            mock_db.query.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_row]
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service.get_contacts()
            assert len(result) == 1
            assert result[0]["username"] == "user1"

    def test_with_keyword(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service.get_contacts(keyword="test")
            assert result == []

    def test_db_error_returns_empty(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service.get_contacts()
            assert result == []


# ---------------------------------------------------------------------------
# scan_messages
# ---------------------------------------------------------------------------


class TestScanMessages:
    def test_db_path_not_exists(self, service, monkeypatch):
        monkeypatch.delenv("WECHAT_MSG_DB_PATH", raising=False)
        with patch("app.utils.path_utils.get_resource_path", return_value="/nonexistent/path"), \
             patch("os.path.exists", return_value=False):
            result = service.scan_messages()
            assert result == []

    def test_import_error(self, service, monkeypatch):
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/tmp/fake.db")
        with patch("app.utils.path_utils.get_resource_path", return_value="/tmp"), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", return_value=False), \
             patch.dict("sys.modules", {"wechat_db_read": None}):
            result = service.scan_messages()
            assert result == []

    def test_general_exception(self, service, monkeypatch):
        with patch("app.utils.path_utils.get_resource_path", side_effect=RuntimeError("err")):
            result = service.scan_messages()
            assert result == []


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task
# ---------------------------------------------------------------------------


class TestInsertOrIgnoreWechatTask:
    def test_empty_raw_text_returns_none(self, service):
        result = service._insert_or_ignore_wechat_task(
            contact_id=1,
            username="u",
            display_name="d",
            message_id="m",
            msg_timestamp=0,
            raw_text="",
        )
        assert result is None

    def test_insert_success(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_task = MagicMock()
            mock_task.id = 42
            mock_db.add = MagicMock()
            mock_db.commit = MagicMock()
            mock_db.refresh = MagicMock()
            # Make refresh set the id
            def set_id(task):
                task.id = 42
            mock_db.refresh.side_effect = set_id
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username="u",
                display_name="d",
                message_id="m1",
                msg_timestamp=0,
                raw_text="test message",
            )
            assert result == 42

    def test_existing_task_returns_id(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_existing = MagicMock()
            mock_existing.id = 10
            mock_db.query.return_value.filter.return_value.first.return_value = mock_existing
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username="u",
                display_name="d",
                message_id="m1",
                msg_timestamp=0,
                raw_text="test",
            )
            assert result == 10

    def test_integrity_error_falls_back(self, service):
        from sqlalchemy.exc import IntegrityError

        # IntegrityError is a subclass of RECOVERABLE_ERRORS, so the
        # first except block catches it, not the IntegrityError handler.
        # The first except block just returns None since it can't find existing.
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.add.side_effect = IntegrityError("stmt", "params", Exception("orig"))
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username="u",
                display_name="d",
                message_id="m1",
                msg_timestamp=0,
                raw_text="test",
            )
            # IntegrityError is caught by RECOVERABLE_ERRORS, returns None
            assert result is None

    def test_general_error_returns_none(self, service):
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=RuntimeError("db err"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username="u",
                display_name="d",
                message_id="m1",
                msg_timestamp=0,
                raw_text="test",
            )
            assert result is None
