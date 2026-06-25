"""app/services/wechat_task_service WechatTaskService 覆盖补强（第二波）。

聚焦未覆盖分支：
- ``_insert_or_ignore_wechat_task`` IntegrityError 专用 handler 命中已存在行（行 85）。
- ``scan_messages`` 完整 happy-path：wechat_cv 路径注入 sys.path、读取行、过滤、
  插入、聚合 new_tasks（行 118,125,131-143,146-149,152,161-162,174-175）。
- ``recognize_order`` / ``recognize_shipment`` 的 except 分支（行 283-285,327-329）。
- ``process_message`` 的 shipment 分支与 result 失败→pending 分支（行 223,231）。
- ``_process_order_message`` / ``_process_shipment_message`` 的失败/异常分支
  （行 580-582,592,609-611）。

所有外部依赖（DB / 文件系统 / wechat_db_read 模块）均被 mock，离线确定性。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.wechat_task_service import WechatTaskService


@pytest.fixture
def service():
    return WechatTaskService()


def _ctx(mock_db):
    """构造一个 get_db() 上下文管理器返回值的 helper。"""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_db)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task —— IntegrityError 专用 handler 找到已存在行（行 85）
# ---------------------------------------------------------------------------


class TestInsertIntegrityHandlerHitsExisting:
    def test_integrity_error_then_finds_existing_returns_id(self, service):
        """db.add 抛 IntegrityError → 专用 handler 二次查询命中已存在行 → 返回其 id。"""
        from sqlalchemy.exc import IntegrityError

        first_db = MagicMock()
        # 第一次进入：existing 查询返回 None（走到 add），add 抛 IntegrityError
        first_db.query.return_value.filter.return_value.first.return_value = None
        first_db.add.side_effect = IntegrityError("stmt", "params", Exception("dup"))

        recovery_db = MagicMock()
        existing = MagicMock()
        existing.id = 777
        recovery_db.query.return_value.filter.return_value.first.return_value = existing

        # 两次 get_db() 调用：第一次返回 first_db，第二次（handler 内）返回 recovery_db
        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.side_effect = [_ctx(first_db), _ctx(recovery_db)]
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username="alice",
                display_name="Alice",
                message_id="msg-1",
                msg_timestamp=123,
                raw_text="规格10桶产品",
                task_type="shipment_order",
            )
        assert result == 777
        # 确认确实走了 IntegrityError 的二次查询路径
        assert mock_get_db.call_count == 2

    def test_integrity_error_no_message_id_returns_none(self, service):
        """IntegrityError handler 中 message_id/username 缺失 → 不查询 → 返回 None（行 86）。"""
        from sqlalchemy.exc import IntegrityError

        first_db = MagicMock()
        first_db.add.side_effect = IntegrityError("stmt", "params", Exception("dup"))

        recovery_db = MagicMock()

        with patch("app.services.wechat_task_service.get_db") as mock_get_db:
            mock_get_db.side_effect = [_ctx(first_db), _ctx(recovery_db)]
            result = service._insert_or_ignore_wechat_task(
                contact_id=1,
                username=None,
                display_name="Alice",
                message_id=None,
                msg_timestamp=123,
                raw_text="规格10桶产品",
            )
        assert result is None
        # handler 内因 message_id/username 为空跳过查询
        recovery_db.query.assert_not_called()


# ---------------------------------------------------------------------------
# scan_messages —— 完整 happy-path（行 118,125,131-143,146-149,152,161-162,174-175）
# ---------------------------------------------------------------------------


class TestScanMessagesHappyPath:
    def _patch_env(self, monkeypatch):
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/tmp/fake_msg.db")
        monkeypatch.delenv("WECHAT_DB_KEY_CONFIG", raising=False)

    def test_scan_inserts_order_like_rows(self, service, monkeypatch):
        """有效订单类行 → 调用 insert → 聚合进 new_tasks，非订单/空文本行被过滤。"""
        self._patch_env(monkeypatch)

        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {
            "rows": [
                # 命中 _is_order_like_message（含"规格"+"桶"）→ task_type=shipment_order
                {
                    "msgId": "m100",
                    "talker": "alice",
                    "displayName": "Alice",
                    "createTime": "1700000000",
                    "content": "  规格10桶产品A  ",
                },
                # 空文本 → continue（行 142-143）
                {
                    "msgId": "m101",
                    "talker": "bob",
                    "displayName": "Bob",
                    "createTime": 0,
                    "content": "   ",
                },
                # 非订单类（无"规格"）→ _is_order_like_message False → continue（行 146-147）
                {
                    "localId": "55",
                    "talker": "carol",
                    "displayName": "Carol",
                    "createTime": 1700000002,
                    "content": "你好今天天气不错",
                },
            ]
        }

        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                side_effect=lambda *parts: "/some/" + "/".join(parts),
            ),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch.dict(sys.modules, {"wechat_db_read": fake_module}),
            patch.object(service, "_insert_or_ignore_wechat_task", return_value=9001) as mock_ins,
        ):
            result = service.scan_messages(contact_id=42, limit=50)

        # 仅第一行被识别并插入
        assert len(result) == 1
        item = result[0]
        assert item["id"] == 9001
        assert item["username"] == "alice"
        assert item["display_name"] == "Alice"
        assert item["message_id"] == "m100"
        assert item["msg_timestamp"] == 1700000000
        assert item["raw_text"] == "规格10桶产品A"  # 已 strip
        assert item["task_type"] == "shipment_order"

        # insert 仅被订单类行调用一次，且参数透传正确
        mock_ins.assert_called_once()
        kwargs = mock_ins.call_args.kwargs
        assert kwargs["contact_id"] == 42
        assert kwargs["username"] == "alice"
        assert kwargs["message_id"] == "m100"
        assert kwargs["task_type"] == "shipment_order"

        # get_recent_messages 以 limit 透传调用
        fake_module.get_recent_messages.assert_called_once()
        assert fake_module.get_recent_messages.call_args.kwargs["limit"] == 50

    def test_scan_insert_returns_none_skips_task(self, service, monkeypatch):
        """insert 返回 None（task_id falsy）→ 不进入 new_tasks（行 161 False 分支）。"""
        self._patch_env(monkeypatch)

        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {
            "rows": [
                {
                    "msgId": "m200",
                    "talker": "dave",
                    "displayName": "Dave",
                    "createTime": 1700000005,
                    "content": "规格5公斤产品X",
                }
            ]
        }

        with (
            patch("app.utils.path_utils.get_resource_path", return_value="/some/path"),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch.dict(sys.modules, {"wechat_db_read": fake_module}),
            patch.object(service, "_insert_or_ignore_wechat_task", return_value=None),
        ):
            result = service.scan_messages()

        assert result == []

    def test_scan_empty_rows_returns_empty(self, service, monkeypatch):
        """get_recent_messages 返回空 rows → 提前返回 []（行 131-133）。"""
        self._patch_env(monkeypatch)

        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {"rows": []}

        with (
            patch("app.utils.path_utils.get_resource_path", return_value="/some/path"),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch.dict(sys.modules, {"wechat_db_read": fake_module}),
        ):
            result = service.scan_messages()

        assert result == []

    def test_scan_inserts_sys_path_when_cv_dir_present(self, service, monkeypatch):
        """wechat_cv 目录存在且不在 sys.path → 插入 sys.path（行 117-118）。"""
        self._patch_env(monkeypatch)

        cv_dir = "/unique/wechat_cv_dir_for_test"
        # 确保该路径初始不在 sys.path
        assert cv_dir not in sys.path

        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {"rows": []}

        def fake_resource(*parts):
            if parts == ("wechat_cv",):
                return cv_dir
            return "/some/path"

        try:
            with (
                patch("app.utils.path_utils.get_resource_path", side_effect=fake_resource),
                patch("os.path.exists", return_value=True),
                patch("os.path.isdir", return_value=True),
                patch.dict(sys.modules, {"wechat_db_read": fake_module}),
            ):
                service.scan_messages()
            assert cv_dir in sys.path
        finally:
            if cv_dir in sys.path:
                sys.path.remove(cv_dir)


# ---------------------------------------------------------------------------
# recognize_order / recognize_shipment —— except 分支（行 283-285,327-329）
# ---------------------------------------------------------------------------


class TestRecognizeExceptionBranches:
    def test_recognize_order_recoverable_error_returns_none(self, service):
        """re.search 抛 ValueError（RECOVERABLE）→ except 分支返回 None（行 283-285）。

        注意：RECOVERABLE_ERRORS 刻意排除 TypeError/AttributeError（程序 bug 应冒泡为
        500），因此需触发 ValueError 这类“可恢复”错误才会命中 except。
        """
        with patch(
            "app.services.wechat_task_service.re.search",
            side_effect=ValueError("boom"),
        ):
            assert service.recognize_order("10 箱 苹果") is None

    def test_recognize_shipment_recoverable_error_returns_none(self, service):
        """re.search 抛 ValueError（RECOVERABLE）→ except 分支返回 None（行 327-329）。"""
        with patch(
            "app.services.wechat_task_service.re.search",
            side_effect=ValueError("boom"),
        ):
            assert service.recognize_shipment("发货 ：10 箱 苹果") is None


# ---------------------------------------------------------------------------
# process_message —— shipment 分支 + 失败→pending 分支（行 223,231）
# ---------------------------------------------------------------------------


class TestProcessMessageBranches:
    def test_shipment_branch_calls_processor(self, service):
        """消息识别为 shipment（非 order）→ 走 _process_shipment_message（行 222-223）。"""
        task = {"raw_text": "发货 ：苹果已发出"}
        with (
            patch.object(service, "_get_task", return_value=task),
            patch.object(service, "_update_task_status", return_value=True) as mock_upd,
            patch.object(
                service,
                "_process_shipment_message",
                return_value={"success": True, "message": "ok"},
            ) as mock_ship,
        ):
            result = service.process_message(5)

        assert result["success"] is True
        mock_ship.assert_called_once_with(task)
        # 成功 → 状态置 done
        mock_upd.assert_called_once_with(5, "done")

    def test_result_failure_sets_pending(self, service):
        """处理结果 success=False → 状态置 pending（行 231 else 分支）。"""
        task = {"raw_text": "10 箱 苹果"}  # 识别为 order
        with (
            patch.object(service, "_get_task", return_value=task),
            patch.object(service, "_update_task_status", return_value=True) as mock_upd,
            patch.object(
                service,
                "_process_order_message",
                return_value={"success": False, "message": "无法解析订单信息"},
            ),
        ):
            result = service.process_message(7)

        assert result["success"] is False
        mock_upd.assert_called_once_with(7, "pending")


# ---------------------------------------------------------------------------
# _process_order_message —— 失败/异常分支（行 559-560,580-582）
# ---------------------------------------------------------------------------


class TestProcessOrderMessage:
    def test_unparseable_returns_failure(self, service):
        """recognize_order 返回 None → 返回失败（行 559-560）。"""
        with patch.object(service, "recognize_order", return_value=None):
            result = service._process_order_message({"raw_text": "无关消息"})
        assert result["success"] is False
        assert "无法解析订单信息" in result["message"]

    def test_exception_returns_failure(self, service):
        """recognize_order 抛 ValueError（RECOVERABLE）→ except 分支返回失败（行 580-582）。"""
        with patch.object(service, "recognize_order", side_effect=ValueError("boom")):
            result = service._process_order_message({"raw_text": "10 箱 苹果"})
        assert result["success"] is False
        assert "处理失败" in result["message"]

    def test_success_path(self, service):
        """成功解析订单 → 返回 success 与 order_info。"""
        order = {
            "type": "order",
            "quantity": 10,
            "unit": "箱 ",
            "product": "苹果",
            "raw_text": "10 箱 苹果",
        }
        with patch.object(service, "recognize_order", return_value=order):
            result = service._process_order_message({"raw_text": "10 箱 苹果"})
        assert result["success"] is True
        assert result["order_info"] == order


# ---------------------------------------------------------------------------
# _process_shipment_message —— 失败/异常分支（行 591-592,609-611）
# ---------------------------------------------------------------------------


class TestProcessShipmentMessage:
    def test_unparseable_returns_failure(self, service):
        """recognize_shipment 返回 None → 返回失败（行 591-592）。"""
        with patch.object(service, "recognize_shipment", return_value=None):
            result = service._process_shipment_message({"raw_text": "无关消息"})
        assert result["success"] is False
        assert "无法解析发货单信息" in result["message"]

    def test_exception_returns_failure(self, service):
        """recognize_shipment 抛 ValueError（RECOVERABLE）→ except 分支返回失败（行 609-611）。"""
        with patch.object(service, "recognize_shipment", side_effect=ValueError("boom")):
            result = service._process_shipment_message({"raw_text": "发货 ：10 箱 苹果"})
        assert result["success"] is False
        assert "处理失败" in result["message"]

    def test_success_path(self, service):
        """成功解析发货单 → 返回 success 与 shipment_info。"""
        shipment = {
            "type": "shipment",
            "content": "10 箱 苹果",
            "products": None,
            "raw_text": "发货 ：10 箱 苹果",
        }
        with patch.object(service, "recognize_shipment", return_value=shipment):
            result = service._process_shipment_message({"raw_text": "发货 ：10 箱 苹果"})
        assert result["success"] is True
        assert result["shipment_info"] == shipment
