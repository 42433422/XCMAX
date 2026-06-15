"""mobile_api_extensions 测试 — 覆盖配对、设备注册/注销、同步、QR 确认等。

由于 mobile_api 和 mobile_api_extensions 之间存在循环导入，
必须通过 create_fastapi_app 创建完整应用来测试路由。
纯函数和 Pydantic 模型测试需要先解析循环导入。
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    """确保 mobile_api_extensions 模块已加载（解析循环导入）。

    必须先导入 mobile_api，它会触发 mobile_api_extensions 的完整加载。
    直接导入 mobile_api_extensions 会触发循环导入错误。
    """
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("LAN_CIDR_GUARD_ENABLED", "0")
    from app.fastapi_app.factory import create_fastapi_app
    return TestClient(create_fastapi_app(enable_cors=False), raise_server_exceptions=False)


@pytest.fixture
def ext_mod():
    """获取已解析的 mobile_api_extensions 模块。"""
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


class TestGuessLanIpv4:
    def test_returns_string(self, ext_mod):
        ip = ext_mod._guess_lan_ipv4()
        assert isinstance(ip, str)
        assert len(ip) > 0


class TestPairingIssueHost:
    def test_localhost_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            host = ext_mod._pairing_issue_host("127.0.0.1")
            assert host == "192.168.1.100"

    def test_localhost_name_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            host = ext_mod._pairing_issue_host("localhost")
            assert host == "192.168.1.100"

    def test_0000_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            host = ext_mod._pairing_issue_host("0.0.0.0")
            assert host == "192.168.1.100"

    def test_real_ip_kept(self, ext_mod):
        host = ext_mod._pairing_issue_host("192.168.1.50")
        assert host == "192.168.1.50"

    def test_empty_defaults(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            host = ext_mod._pairing_issue_host("")
            assert host == "192.168.1.100"


# ---------------------------------------------------------------------------
# 配对路由（通过完整应用测试）
# ---------------------------------------------------------------------------


class TestPairingIssue:
    def test_issue_success(self, client: TestClient):
        r = client.post(
            "/api/mobile/v1/pairing/issue",
            json={"host": "192.168.1.10", "port": 5000},
        )
        assert r.status_code == 200
        assert r.json().get("success") is True


class TestPairingExchange:
    def test_exchange_by_nonce(self, client: TestClient):
        issue = client.post(
            "/api/mobile/v1/pairing/issue",
            json={"host": "192.168.1.10", "port": 5000},
        )
        nonce = issue.json().get("data", {}).get("nonce")
        assert nonce
        r = client.post("/api/mobile/v1/pairing/exchange", json={"nonce": nonce})
        assert r.status_code == 200
        assert r.json().get("data", {}).get("host") == "192.168.1.10"

    def test_exchange_no_credentials(self, client: TestClient):
        r = client.post("/api/mobile/v1/pairing/exchange", json={"code": "", "nonce": ""})
        assert r.status_code == 400


class TestMobileModsRequiresAuth:
    def test_unauthorized(self, client: TestClient):
        r = client.get("/api/mobile/v1/mods")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# _mobile_mod_items — get_mod_manager 是延迟导入，需要在源模块打补丁
# ---------------------------------------------------------------------------


class TestMobileModItems:
    def test_empty_list(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = []
            items = ext_mod._mobile_mod_items()
            assert items == []

    def test_dict_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "mod-a", "name": "Mod A"},
                {"mod_id": "mod-b", "title": "Mod B"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 2
            assert items[0]["id"] == "mod-a"

    def test_object_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mod = MagicMock()
            mod.id = "mod-obj"
            mod.name = "Obj Mod"
            mod.mod_id = ""
            mod.title = ""
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert items[0]["id"] == "mod-obj"

    def test_exception_returns_empty(self, ext_mod):
        # RECOVERABLE_ERRORS 包含 RuntimeError/ImportError，不包含通用 Exception
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager", side_effect=RuntimeError("fail")):
            items = ext_mod._mobile_mod_items()
            assert items == []

    def test_limit_100(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(150)
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 100


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestDeviceRegisterBody:
    def test_valid(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        assert body.fcm_token == "a" * 10
        assert body.push_provider == "fcm"

    def test_default_values(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        assert body.platform == "android"
        assert body.product_sku == "personal"


class TestPairingExchangeBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.PairingExchangeBody()
        assert body.nonce == ""
        assert body.code == ""


class TestPairingIssueBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.PairingIssueBody()
        assert body.host == "127.0.0.1"
        assert body.port == 5000


class TestSyncPullBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.SyncPullBody()
        assert body.since_cursor == 0


class TestSyncPushItem:
    def test_valid(self, ext_mod):
        item = ext_mod.SyncPushItem(entity_type="customer", entity_id="1")
        assert item.entity_type == "customer"
        assert item.operation == "update"


class TestSyncAckBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.SyncAckBody()
        assert body.cursor == 0
