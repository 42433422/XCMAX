"""Comprehensive tests for app.fastapi_routes.service_bridge.

Covers: config get/put, requests CRUD, instances, stats, outbox, sync, ping-main,
and all helper functions.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fastapi_routes.service_bridge import (
    BridgeConfigUpdate,
    OutboxCreate,
    ServiceRequestCreate,
    ServiceRequestRespond,
    _get_config_value,
    _get_instance_name,
    _get_or_create_instance_id,
    _set_config_value,
)

# ---------------------------------------------------------------------------
# _get_instance_name
# ---------------------------------------------------------------------------


class TestGetInstanceName:
    def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SERVICE_BRIDGE_INSTANCE_NAME", None)
            assert _get_instance_name() == "XCAGI 宿主"

    def test_custom(self):
        with patch.dict(os.environ, {"SERVICE_BRIDGE_INSTANCE_NAME": "My Instance"}):
            assert _get_instance_name() == "My Instance"

    def test_empty_env(self):
        with patch.dict(os.environ, {"SERVICE_BRIDGE_INSTANCE_NAME": ""}):
            assert _get_instance_name() == ""


# ---------------------------------------------------------------------------
# _get_or_create_instance_id
# ---------------------------------------------------------------------------


class TestGetOrCreateInstanceId:
    def test_format(self):
        with patch("os.path.exists", return_value=False), patch("os.makedirs"):
            result = _get_or_create_instance_id()
            assert result.startswith("xcagi-host-")

    def test_reads_cached(self):
        with patch("os.path.exists", return_value=True):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.read.return_value = "xcagi-host-cached123"
            with patch("builtins.open", return_value=mock_file):
                result = _get_or_create_instance_id()
                assert result == "xcagi-host-cached123"

    def test_empty_cached_generates_new(self):
        with patch("os.path.exists", return_value=True):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.read.return_value = ""
            with patch("builtins.open", return_value=mock_file), patch("os.makedirs"):
                result = _get_or_create_instance_id()
                assert result.startswith("xcagi-host-")

    def test_write_error(self):
        with (
            patch("os.path.exists", return_value=False),
            patch("os.makedirs", side_effect=OSError("no write")),
        ):
            result = _get_or_create_instance_id()
            assert result.startswith("xcagi-host-")


# ---------------------------------------------------------------------------
# _get_config_value
# ---------------------------------------------------------------------------


class TestGetConfigValue:
    def test_from_db(self):
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.config_value = "db_value"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cfg
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=mock_db):
            result = _get_config_value("test_key")
            assert result == "db_value"

    def test_from_env_fallback(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.fastapi_routes.service_bridge.get_db", return_value=mock_db),
            patch.dict(os.environ, {"SERVICE_BRIDGE_TEST_KEY": "env_value"}),
        ):
            result = _get_config_value("test_key")
            assert result == "env_value"

    def test_default(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.fastapi_routes.service_bridge.get_db", return_value=mock_db),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = _get_config_value("test_key", default="fallback")
            assert result == "fallback"


# ---------------------------------------------------------------------------
# _set_config_value
# ---------------------------------------------------------------------------


class TestSetConfigValue:
    def test_update_existing(self):
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cfg
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=mock_db):
            _set_config_value("key", "new_val", "desc")
            assert mock_cfg.config_value == "new_val"
            assert mock_cfg.description == "desc"

    def test_create_new(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=mock_db):
            _set_config_value("key", "val")
            mock_db.add.assert_called_once()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestServiceRequestCreate:
    def test_defaults(self):
        body = ServiceRequestCreate(
            source_instance_id="inst-1",
            source_instance_name="Test",
            title="Help",
        )
        assert body.priority == "normal"
        assert body.request_type == "general"
        assert body.description is None
        assert body.extra_data is None


class TestServiceRequestRespond:
    def test_defaults(self):
        body = ServiceRequestRespond(response="done")
        assert body.status == "resolved"
        assert body.responded_by is None


class TestBridgeConfigUpdate:
    def test_defaults(self):
        body = BridgeConfigUpdate()
        assert body.main_server_url is None
        assert body.instance_name is None


class TestOutboxCreate:
    def test_defaults(self):
        body = OutboxCreate(title="Test")
        assert body.priority == "normal"
        assert body.request_type == "general"


# ---------------------------------------------------------------------------
# Route handler tests (direct function calls with mocked DB)
# ---------------------------------------------------------------------------


def _mock_db_ctx(mock_db: MagicMock) -> MagicMock:
    """Create a context manager mock for get_db()."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_returns_config(self):
        from app.fastapi_routes.service_bridge import get_config

        with (
            patch(
                "app.fastapi_routes.service_bridge._get_or_create_instance_id",
                return_value="inst-1",
            ),
            patch("app.fastapi_routes.service_bridge._get_instance_name", return_value="Test"),
            patch(
                "app.fastapi_routes.service_bridge._get_config_value", return_value="http://main"
            ),
        ):
            result = await get_config()
            assert result["success"] is True
            assert result["data"]["instance_id"] == "inst-1"


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_update_main_server_url(self):
        from app.fastapi_routes.service_bridge import update_config

        with patch("app.fastapi_routes.service_bridge._set_config_value") as mock_set:
            result = await update_config(BridgeConfigUpdate(main_server_url="http://test"))
            assert result["success"] is True
            mock_set.assert_called_once_with("main_server_url", "http://test", "主软件服务器地址")

    @pytest.mark.asyncio
    async def test_update_instance_name(self):
        from app.fastapi_routes.service_bridge import update_config

        with patch("app.fastapi_routes.service_bridge._set_config_value") as mock_set:
            result = await update_config(BridgeConfigUpdate(instance_name="Test"))
            assert result["success"] is True
            mock_set.assert_called_once_with("instance_name", "Test", "本实例名称")

    @pytest.mark.asyncio
    async def test_empty_update(self):
        from app.fastapi_routes.service_bridge import update_config

        with patch("app.fastapi_routes.service_bridge._set_config_value") as mock_set:
            result = await update_config(BridgeConfigUpdate())
            assert result["success"] is True
            mock_set.assert_not_called()


class TestReceiveRequest:
    @pytest.mark.asyncio
    async def test_invalid_priority(self):
        from fastapi import HTTPException

        from app.fastapi_routes.service_bridge import receive_request

        body = ServiceRequestCreate(
            source_instance_id="inst-1",
            source_instance_name="Test",
            title="Help",
            priority="invalid_priority",
        )
        mock_db = MagicMock()
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            with pytest.raises(HTTPException) as exc_info:
                await receive_request(body)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_request(self):
        from app.fastapi_routes.service_bridge import receive_request

        mock_db = MagicMock()
        mock_req = MagicMock()
        mock_req.to_dict.return_value = {"id": 1, "title": "Help"}
        # The route creates ServiceRequest internally, then calls db.add and db.flush
        # We need to mock the ServiceRequest class
        with (
            patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.db.models.service_request.ServiceRequest", return_value=mock_req),
        ):
            body = ServiceRequestCreate(
                source_instance_id="inst-1",
                source_instance_name="Test",
                title="Help",
                priority="normal",
            )
            result = await receive_request(body)
            assert result["success"] is True


class TestListRequests:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        from app.fastapi_routes.service_bridge import list_requests

        mock_db = MagicMock()
        mock_req = MagicMock()
        mock_req.to_dict.return_value = {"id": 1}
        mock_db.query.return_value.count.return_value = 1
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_req
        ]
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await list_requests(page=1, per_page=20)
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_filters(self):
        from app.fastapi_routes.service_bridge import list_requests

        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.filter.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await list_requests(
                status="pending", source_instance_id="inst-1", page=1, per_page=20
            )
            assert result["success"] is True


class TestGetRequest:
    @pytest.mark.asyncio
    async def test_not_found(self):
        from fastapi import HTTPException

        from app.fastapi_routes.service_bridge import get_request

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            with pytest.raises(HTTPException) as exc_info:
                await get_request(999)
            assert exc_info.value.status_code == 404


class TestRespondRequest:
    @pytest.mark.asyncio
    async def test_invalid_status(self):
        from fastapi import HTTPException

        from app.fastapi_routes.service_bridge import respond_request

        body = ServiceRequestRespond(response="done", status="invalid_status")
        with pytest.raises(HTTPException) as exc_info:
            await respond_request(1, body)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_not_found(self):
        from fastapi import HTTPException

        from app.fastapi_routes.service_bridge import respond_request

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        body = ServiceRequestRespond(response="done", status="resolved")
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            with pytest.raises(HTTPException) as exc_info:
                await respond_request(999, body)
            assert exc_info.value.status_code == 404


class TestListInstances:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        from app.fastapi_routes.service_bridge import list_instances

        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.source_instance_id = "inst-1"
        mock_row.source_instance_name = "Test"
        mock_row.total_requests = 5
        mock_row.pending_count = 2
        mock_db.query.return_value.group_by.return_value.all.return_value = [mock_row]
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await list_instances()
            assert result["success"] is True


class TestGetStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self):
        from app.fastapi_routes.service_bridge import get_stats

        mock_db = MagicMock()
        mock_db.query.return_value.scalar.return_value = 10
        mock_db.query.return_value.filter.return_value.scalar.return_value = 3
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await get_stats()
            assert result["success"] is True


class TestOutboxSend:
    @pytest.mark.asyncio
    async def test_invalid_priority(self):
        from fastapi import HTTPException

        from app.fastapi_routes.service_bridge import send_outbox

        body = OutboxCreate(title="Test", priority="bad")
        with (
            patch(
                "app.fastapi_routes.service_bridge._get_or_create_instance_id",
                return_value="inst-1",
            ),
            patch("app.fastapi_routes.service_bridge._get_config_value", return_value="test"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await send_outbox(body)
            assert exc_info.value.status_code == 400


class TestListOutbox:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        from app.fastapi_routes.service_bridge import list_outbox

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        with (
            patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)),
            patch(
                "app.fastapi_routes.service_bridge._get_or_create_instance_id",
                return_value="inst-1",
            ),
        ):
            result = await list_outbox()
            assert result["success"] is True


class TestSyncOutbox:
    @pytest.mark.asyncio
    async def test_no_main_server(self):
        from app.fastapi_routes.service_bridge import sync_outbox

        with (
            patch(
                "app.fastapi_routes.service_bridge._get_or_create_instance_id",
                return_value="inst-1",
            ),
            patch("app.fastapi_routes.service_bridge._get_config_value", return_value=""),
        ):
            result = await sync_outbox()
            assert result["synced_count"] == 0


class TestPingMain:
    @pytest.mark.asyncio
    async def test_no_main_server(self):
        from app.fastapi_routes.service_bridge import ping_main_server

        with patch("app.fastapi_routes.service_bridge._get_config_value", return_value=""):
            result = await ping_main_server()
            assert result["connected"] is True

    @pytest.mark.asyncio
    async def test_main_server_unreachable(self):
        from app.fastapi_routes.service_bridge import ping_main_server

        with (
            patch(
                "app.fastapi_routes.service_bridge._get_config_value",
                return_value="http://unreachable:9999",
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get.side_effect = RuntimeError("unreachable")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ping_main_server()
            assert result["success"] is False
