"""Tests for app.fastapi_routes.domains.wechat.routes — route handlers with mocked dependencies."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import routes


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _send_wechat_via_automation  (lazy imports → patch source modules)
# ---------------------------------------------------------------------------


class TestSendWechatViaAutomation:
    def test_safe_check_fails(self):
        with patch(
            "app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply",
            return_value=False,
        ):
            result = routes._send_wechat_via_automation("张三", "test msg")
            assert result["success"] is False
            assert "安全校验" in result["message"]

    def test_automation_success(self):
        with patch(
            "app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply",
            return_value="safe msg",
        ), patch(
            "app.desktop_automation.service.get_desktop_automation_service"
        ) as mock_svc:
            mock_svc.return_value.send_wechat_message.return_value = {"success": True}
            result = routes._send_wechat_via_automation("张三", "test msg")
            assert result["success"] is True

    def test_automation_fail_non_windows(self):
        with patch(
            "app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply",
            return_value="safe msg",
        ), patch(
            "app.desktop_automation.service.get_desktop_automation_service"
        ) as mock_svc, patch(
            "app.fastapi_routes.domains.wechat.routes.sys"
        ) as mock_sys:
            mock_sys.platform = "darwin"
            mock_svc.return_value.send_wechat_message.return_value = {
                "success": False,
                "error": "not available",
            }
            result = routes._send_wechat_via_automation("张三", "test msg")
            assert result["success"] is False


# ---------------------------------------------------------------------------
# wechat_tasks  (lazy: from app.application import get_wechat_task_app_service)
# ---------------------------------------------------------------------------


class TestWechatTasks:
    def test_success(self, client: TestClient):
        mock_service = MagicMock()
        mock_service.get_tasks.return_value = [{"id": 1, "raw_text": "test"}]
        with patch(
            "app.application.get_wechat_task_app_service",
            return_value=mock_service,
        ):
            r = client.get("/wechat/tasks")
            assert r.json()["success"] is True
            assert len(r.json()["data"]) == 1

    def test_error(self, client: TestClient):
        with patch(
            "app.application.get_wechat_task_app_service",
            side_effect=Exception("db error"),
        ):
            r = client.get("/wechat/tasks")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_starred_messages
# ---------------------------------------------------------------------------


class TestWechatStarredMessages:
    def test_group_type_with_sync(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_bound_groups_from_live_wechat"
        ) as mock_sync, patch(
            "app.services.wechat_group_customer_bridge.build_starred_group_feed",
            return_value=[{"id": 1}],
        ):
            r = client.get(
                "/wechat/starred-messages",
                params={"type": "group", "sync": True, "market_user_id": 1},
            )
            assert r.json()["success"] is True

    def test_group_type_sync_no_market_user_id(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_group_messages"
        ) as mock_sync, patch(
            "app.services.wechat_group_customer_bridge.build_starred_group_feed",
            return_value=[],
        ):
            r = client.get(
                "/wechat/starred-messages",
                params={"type": "group", "sync": True},
            )
            assert r.json()["success"] is True

    def test_contact_type(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = [
            {"id": 1, "contact_name": "张三", "remark": "", "contact_type": "contact"}
        ]
        mock_svc.get_contact_context.return_value = [
            {"content": "hello", "timestamp": 1700000000}
        ]
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ), patch(
            "app.services.wechat_group_customer_bridge._latest_context_message",
            return_value={"content": "hello", "timestamp": 1700000000},
        ):
            r = client.get("/wechat/starred-messages", params={"type": "contact"})
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.build_starred_group_feed",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat/starred-messages", params={"type": "group"})
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_groups_sync_messages
# ---------------------------------------------------------------------------


class TestWechatGroupsSyncMessages:
    def test_success(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_group_messages",
            return_value={"success": True, "synced": 5, "failed": 0},
        ):
            r = client.post("/wechat/groups/sync")
            assert r.json()["success"] is True

    def test_all_failed(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_group_messages",
            return_value={"success": True, "synced": 0, "failed": 3},
        ):
            r = client.post("/wechat/groups/sync")
            assert r.json()["success"] is False

    def test_error(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_group_messages",
            side_effect=Exception("db error"),
        ):
            r = client.post("/wechat/groups/sync")
            assert r.status_code == 500

    def test_with_body_market_user_id(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.sync_group_messages",
            return_value={"success": True, "synced": 1, "failed": 0},
        ):
            r = client.post(
                "/wechat/groups/sync",
                json={"market_user_id": 42, "group_limit": 10},
            )
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_groups_list
# ---------------------------------------------------------------------------


class TestWechatGroupsList:
    def test_success(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.list_group_contacts",
            return_value=[{"id": 1, "name": "群1"}],
        ):
            r = client.get("/wechat/groups")
            assert r.json()["success"] is True
            assert len(r.json()["data"]) == 1

    def test_error(self, client: TestClient):
        with patch(
            "app.services.wechat_group_customer_bridge.list_group_contacts",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat/groups")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contacts_list_api
# ---------------------------------------------------------------------------


class TestWechatContactsListApi:
    def test_erp_dispatch(self, client: TestClient):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value={"success": True, "data": []},
        ):
            r = client.get("/wechat/contacts")
            assert r.json()["success"] is True

    def test_fallback_to_app_service(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = [{"id": 1}]
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value=None,
        ), patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat/contacts")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            side_effect=Exception("fail"),
        ), patch(
            "app.application.get_wechat_contact_app_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat/contacts")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contact_get_api
# ---------------------------------------------------------------------------


class TestWechatContactGetApi:
    def test_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = {"id": 1, "contact_name": "张三"}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat/contacts/1")
            assert r.json()["success"] is True

    def test_not_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = None
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat/contacts/999")
            assert r.status_code == 404

    def test_error(self, client: TestClient):
        with patch(
            "app.application.get_wechat_contact_app_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat/contacts/1")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contact_delete_api
# ---------------------------------------------------------------------------


class TestWechatContactDeleteApi:
    def test_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.delete_contact.return_value = {"success": True}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.delete("/wechat/contacts/1")
            assert r.status_code == 200

    def test_fail(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.delete_contact.return_value = {"success": False, "message": "not found"}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.delete("/wechat/contacts/1")
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# wechat_contact_context_api
# ---------------------------------------------------------------------------


class TestWechatContactContextApi:
    def test_without_refresh(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_context.return_value = [{"content": "hi"}]
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat/contacts/1/context")
            assert r.json()["success"] is True
            assert r.json()["count"] == 1

    def test_with_refresh(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_context.return_value = []
        mock_svc.refresh_messages = MagicMock()
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ), patch(
            "app.services.wechat_decrypt_autoconfig.prepare_wechat_message_db_for_read",
            create=True,
        ):
            r = client.get("/wechat/contacts/1/context", params={"refresh": True})
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.application.get_wechat_contact_app_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat/contacts/1/context")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contacts_post
# ---------------------------------------------------------------------------


class TestWechatContactsPost:
    def test_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.add_contact.return_value = {"success": True}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/contacts", json={"contact_name": "张三"})
            assert r.status_code == 200

    def test_empty_name(self, client: TestClient):
        r = client.post("/wechat/contacts", json={"contact_name": ""})
        assert r.status_code == 400

    def test_missing_name(self, client: TestClient):
        r = client.post("/wechat/contacts", json={})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# wechat_contacts_put
# ---------------------------------------------------------------------------


class TestWechatContactsPut:
    def test_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.update_contact.return_value = {"success": True}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.put("/wechat/contacts/1", json={"contact_name": "新名"})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# wechat_contacts_star
# ---------------------------------------------------------------------------


class TestWechatContactsStar:
    def test_with_star_contact_method(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.star_contact = MagicMock(return_value={"success": True})
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/contacts/1/star", json={"starred": True})
            assert r.status_code == 200

    def test_without_star_contact_method(self, client: TestClient):
        mock_svc = MagicMock(spec=[])
        mock_svc.update_contact = MagicMock(return_value={"success": True})
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/contacts/1/star", json={"starred": False})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# wechat_contacts_unstar_all
# ---------------------------------------------------------------------------


class TestWechatContactsUnstarAll:
    def test_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.unstar_all.return_value = {"success": True, "count": 0}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/contacts/unstar-all")
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_status
# ---------------------------------------------------------------------------


class TestWechatStatus:
    def test_error(self, client: TestClient):
        with patch(
            "app.utils.path_utils.get_resource_path",
            side_effect=RuntimeError("no resource"),
        ):
            r = client.get("/wechat/status")
            assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# wechat_test
# ---------------------------------------------------------------------------


class TestWechatTest:
    def test_ok(self, client: TestClient):
        r = client.get("/wechat/test")
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_task_confirm / wechat_task_ignore
# ---------------------------------------------------------------------------


class TestWechatTaskActions:
    def test_confirm_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.confirm_task.return_value = {"success": True}
        with patch(
            "app.application.get_wechat_task_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/task/1/confirm")
            assert r.status_code == 200

    def test_confirm_fail(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.confirm_task.return_value = {"success": False, "message": "not found"}
        with patch(
            "app.application.get_wechat_task_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/task/1/confirm")
            assert r.status_code == 400

    def test_ignore_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.ignore_task.return_value = {"success": True}
        with patch(
            "app.application.get_wechat_task_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/task/1/ignore")
            assert r.status_code == 200

    def test_ignore_fail(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.ignore_task.return_value = {"success": False, "message": "not found"}
        with patch(
            "app.application.get_wechat_task_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat/task/1/ignore")
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# wechat_scan
# ---------------------------------------------------------------------------


class TestWechatScan:
    def test_success(self, client: TestClient):
        mock_task = MagicMock()
        mock_task.id = "task-123"
        mock_scan = MagicMock()
        mock_scan.delay = MagicMock(return_value=mock_task)
        with patch(
            "app.tasks.wechat_tasks.scan_wechat_messages",
            mock_scan,
            create=True,
        ):
            r = client.post("/wechat/scan", json={"contact_id": 1})
            assert r.status_code == 202
            assert r.json()["success"] is True
            assert r.json()["task_id"] == "task-123"

    def test_error(self, client: TestClient):
        with patch(
            "app.tasks.wechat_tasks.scan_wechat_messages",
            side_effect=ImportError("no module"),
            create=True,
        ):
            r = client.post("/wechat/scan", json={})
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contacts_send_message
# ---------------------------------------------------------------------------


class TestWechatContactsSendMessage:
    def test_empty_contact_name(self, client: TestClient):
        r = client.post("/wechat_contacts/send_message", json={"contact_name": "", "message": "hi"})
        assert r.status_code == 400

    def test_empty_message(self, client: TestClient):
        r = client.post("/wechat_contacts/send_message", json={"contact_name": "张三", "message": ""})
        assert r.status_code == 400

    def test_send_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            return_value={"success": True, "message": "已发送"},
        ):
            r = client.post(
                "/wechat_contacts/send_message",
                json={"contact_name": "张三", "message": "hello"},
            )
            assert r.json()["success"] is True

    def test_send_failure(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            return_value={"success": False, "message": "发送失败"},
        ):
            r = client.post(
                "/wechat_contacts/send_message",
                json={"contact_name": "张三", "message": "hello"},
            )
            assert r.status_code == 500

    def test_send_exception(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            side_effect=Exception("unexpected"),
        ):
            r = client.post(
                "/wechat_contacts/send_message",
                json={"contact_name": "张三", "message": "hello"},
            )
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contacts_send_message_to_id
# ---------------------------------------------------------------------------


class TestWechatContactsSendMessageToId:
    def test_empty_message(self, client: TestClient):
        r = client.post("/wechat_contacts/1/send_message", json={"message": ""})
        assert r.status_code == 400

    def test_contact_not_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = None
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.post("/wechat_contacts/999/send_message", json={"message": "hi"})
            assert r.status_code == 404

    def test_send_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = {"contact_name": "张三"}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ), patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            return_value={"success": True, "message": "已发送"},
        ):
            r = client.post("/wechat_contacts/1/send_message", json={"message": "hello"})
            assert r.json()["success"] is True

    def test_send_failure(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = {"contact_name": "张三"}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ), patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            return_value={"success": False, "message": "发送失败"},
        ):
            r = client.post("/wechat_contacts/1/send_message", json={"message": "hello"})
            assert r.status_code == 500

    def test_send_exception(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = {"contact_name": "张三"}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ), patch(
            "app.fastapi_routes.domains.wechat.routes._send_wechat_via_automation",
            side_effect=Exception("unexpected"),
        ):
            r = client.post("/wechat_contacts/1/send_message", json={"message": "hello"})
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# wechat_contacts_get_by_id
# ---------------------------------------------------------------------------


class TestWechatContactsGetById:
    def test_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = {"id": 1}
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat_contacts/1")
            assert r.json()["success"] is True

    def test_not_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_contact_by_id.return_value = None
        with patch(
            "app.application.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            r = client.get("/wechat_contacts/999")
            assert r.status_code == 404

    def test_error(self, client: TestClient):
        with patch(
            "app.application.get_wechat_contact_app_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/wechat_contacts/1")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# ensure_contact_cache / message_source_size
# ---------------------------------------------------------------------------


class TestWechatFacadeRoutes:
    def test_ensure_contact_cache_get(self, client: TestClient):
        with patch(
            "app.application.facades.wechat_facade.refresh_wechat_contacts_from_decrypt",
            return_value=({"success": True}, 200),
        ):
            r = client.get("/wechat_contacts/ensure_contact_cache")
            assert r.status_code == 200

    def test_ensure_contact_cache_post(self, client: TestClient):
        with patch(
            "app.application.facades.wechat_facade.refresh_wechat_contacts_from_decrypt",
            return_value=({"success": True}, 200),
        ):
            r = client.post("/wechat_contacts/ensure_contact_cache")
            assert r.status_code == 200

    def test_message_source_size(self, client: TestClient):
        with patch(
            "app.application.facades.wechat_facade.wechat_message_source_size_payload",
            return_value=({"success": True}, 200),
        ):
            r = client.get("/wechat_contacts/message_source_size")
            assert r.status_code == 200
