"""测试 license_guard 模块的 LAN 许可校验中间件。"""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.security.license_guard import (
    _read_cookie,
    _read_header,
    _send_json,
    LanLicenseGuard,
)


# ---------------------------------------------------------------------------
# _read_cookie
# ---------------------------------------------------------------------------

class TestReadCookie:
    def test_finds_cookie(self):
        scope = {
            "headers": [
                (b"cookie", b"session=abc; lan_token=mytoken; other=val"),
            ]
        }
        assert _read_cookie(scope, "lan_token") == "mytoken"

    def test_no_cookie_header(self):
        scope = {"headers": []}
        assert _read_cookie(scope, "lan_token") is None

    def test_cookie_not_present(self):
        scope = {"headers": [(b"cookie", b"session=abc")]}
        assert _read_cookie(scope, "lan_token") is None

    def test_empty_value(self):
        scope = {"headers": [(b"cookie", b"lan_token=")]}
        assert _read_cookie(scope, "lan_token") == ""

    def test_multiple_cookie_headers(self):
        scope = {
            "headers": [
                (b"cookie", b"session=abc"),
                (b"cookie", b"lan_token=tok123"),
            ]
        }
        assert _read_cookie(scope, "lan_token") == "tok123"

    def test_no_headers_key(self):
        scope = {}
        assert _read_cookie(scope, "lan_token") is None

    def test_malformed_cookie_skipped(self):
        scope = {"headers": [(b"cookie", b"novalue; lan_token=good")]}
        assert _read_cookie(scope, "lan_token") == "good"


# ---------------------------------------------------------------------------
# _read_header
# ---------------------------------------------------------------------------

class TestReadHeader:
    def test_finds_header(self):
        scope = {"headers": [(b"x-lan-token", b"mytoken")]}
        assert _read_header(scope, "X-LAN-Token") == "mytoken"

    def test_header_not_present(self):
        scope = {"headers": [(b"content-type", b"text/html")]}
        assert _read_header(scope, "X-LAN-Token") is None

    def test_case_insensitive(self):
        scope = {"headers": [(b"X-LAN-TOKEN", b"mytoken")]}
        assert _read_header(scope, "x-lan-token") == "mytoken"

    def test_no_headers(self):
        scope = {}
        assert _read_header(scope, "X-LAN-Token") is None


# ---------------------------------------------------------------------------
# _send_json
# ---------------------------------------------------------------------------

class TestSendJson:
    @pytest.mark.asyncio
    async def test_sends_json_response(self):
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        await _send_json(mock_send, 401, {"error": "test"})

        assert len(messages) == 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 401
        assert messages[1]["type"] == "http.response.body"
        body = json.loads(messages[1]["body"])
        assert body["error"] == "test"

    @pytest.mark.asyncio
    async def test_sends_with_extra_headers(self):
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        await _send_json(
            mock_send, 200, {"ok": True},
            extra_headers=[(b"x-custom", b"value")]
        )
        assert len(messages) == 2
        header_names = [h[0] for h in messages[0]["headers"]]
        assert b"x-custom" in header_names


# ---------------------------------------------------------------------------
# LanLicenseGuard
# ---------------------------------------------------------------------------

class TestLanLicenseGuard:
    @pytest.fixture
    def mock_app(self):
        app = AsyncMock()
        return app

    @pytest.fixture
    def guard(self, mock_app):
        return LanLicenseGuard(mock_app)

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self, guard, mock_app):
        scope = {"type": "websocket"}
        await guard(scope, MagicMock(), MagicMock())
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_guard_passes(self, guard, mock_app):
        mock_cfg = MagicMock()
        mock_cfg.enabled = False
        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg):
            scope = {"type": "http", "method": "GET", "path": "/api/test"}
            await guard(scope, MagicMock(), MagicMock())
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_passes(self, guard, mock_app):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg):
            scope = {"type": "http", "method": "OPTIONS", "path": "/api/test"}
            await guard(scope, MagicMock(), MagicMock())
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_bypassed_path_passes(self, guard, mock_app):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.lan_guard_path_is_bypassed", return_value=True):
            scope = {"type": "http", "method": "GET", "path": "/health"}
            await guard(scope, MagicMock(), MagicMock())
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_secret_not_ready_returns_503(self, guard):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = False
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg):
            scope = {"type": "http", "method": "GET", "path": "/api/test"}
            await guard(scope, MagicMock(), mock_send)
            assert len(messages) == 2
            assert messages[0]["status"] == 503

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, guard):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = []
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.ensure_schema"), \
             patch("app.security.license_guard.get_client_ip", return_value="10.0.0.1"):
            scope = {"type": "http", "method": "GET", "path": "/api/test", "headers": []}
            await guard(scope, MagicMock(), mock_send)
            assert len(messages) == 2
            assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, guard):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.license_secret = "testsecret1234567890"
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = []
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        from app.security.license_token import TokenError
        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.ensure_schema"), \
             patch("app.security.license_guard.get_client_ip", return_value="10.0.0.1"), \
             patch("app.security.license_guard.parse_token", side_effect=TokenError("bad")):
            scope = {
                "type": "http", "method": "GET", "path": "/api/test",
                "headers": [(b"cookie", b"lan_token=badtoken")],
            }
            await guard(scope, MagicMock(), mock_send)
            assert len(messages) == 2
            assert messages[0]["status"] == 401
            body = json.loads(messages[1]["body"])
            assert body["error"] == "license_invalid"

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, guard):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.license_secret = "testsecret1234567890"
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = []
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        mock_payload = MagicMock()
        mock_payload.is_expired.return_value = True
        mock_payload.jti = "test-jti"

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.ensure_schema"), \
             patch("app.security.license_guard.get_client_ip", return_value="10.0.0.1"), \
             patch("app.security.license_guard.parse_token", return_value=mock_payload):
            scope = {
                "type": "http", "method": "GET", "path": "/api/test",
                "headers": [(b"cookie", b"lan_token=expiredtoken")],
            }
            await guard(scope, MagicMock(), mock_send)
            assert len(messages) == 2
            assert messages[0]["status"] == 401
            body = json.loads(messages[1]["body"])
            assert body["error"] == "license_expired"

    @pytest.mark.asyncio
    async def test_revoked_session_returns_401(self, guard):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.license_secret = "testsecret1234567890"
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = []
        messages = []
        async def mock_send(msg):
            messages.append(msg)

        mock_payload = MagicMock()
        mock_payload.is_expired.return_value = False
        mock_payload.jti = "test-jti"

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.ensure_schema"), \
             patch("app.security.license_guard.get_client_ip", return_value="10.0.0.1"), \
             patch("app.security.license_guard.parse_token", return_value=mock_payload), \
             patch("app.security.license_guard.get_active_session_by_jti", return_value=None):
            scope = {
                "type": "http", "method": "GET", "path": "/api/test",
                "headers": [(b"cookie", b"lan_token=revokedtoken")],
            }
            await guard(scope, MagicMock(), mock_send)
            assert len(messages) == 2
            assert messages[0]["status"] == 401
            body = json.loads(messages[1]["body"])
            assert body["error"] == "license_revoked"

    @pytest.mark.asyncio
    async def test_valid_token_passes(self, guard, mock_app):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.license_secret = "testsecret1234567890"
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = []

        mock_payload = MagicMock()
        mock_payload.is_expired.return_value = False
        mock_payload.jti = "valid-jti"
        mock_payload.exp = 9999999999

        mock_session = MagicMock()
        mock_session.key_id = 1

        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.is_admin = False

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.ensure_schema"), \
             patch("app.security.license_guard.get_client_ip", return_value="10.0.0.1"), \
             patch("app.security.license_guard.parse_token", return_value=mock_payload), \
             patch("app.security.license_guard.get_active_session_by_jti", return_value=mock_session), \
             patch("app.security.license_guard.list_keys", return_value=[mock_key]), \
             patch("app.security.license_guard.touch_session"):
            scope = {
                "type": "http", "method": "GET", "path": "/api/test",
                "headers": [(b"cookie", b"lan_token=validtoken")],
            }
            await guard(scope, MagicMock(), MagicMock())
            mock_app.assert_called_once()
            assert scope["state"]["lan_jti"] == "valid-jti"
            assert scope["state"]["lan_is_admin"] is False

    @pytest.mark.asyncio
    async def test_admin_host_bypass(self, guard, mock_app):
        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = []
        mock_cfg.admin_host_ips = ["127.0.0.1"]

        with patch("app.security.license_guard.get_lan_config", return_value=mock_cfg), \
             patch("app.security.license_guard.get_client_ip", return_value="127.0.0.1"):
            scope = {"type": "http", "method": "GET", "path": "/api/test", "headers": []}
            await guard(scope, MagicMock(), MagicMock())
            mock_app.assert_called_once()
            assert scope["state"].get("lan_admin_host_bypass") is True
