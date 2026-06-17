"""Comprehensive tests for xcmax_admin — covering _require_market_admin_session,
_market_admin_proxy, _digest_local_or_proxy, _collect_mod_modules,
_collect_employee_pack_modules, _inject_digest_api_base, _probe_remote_health_sync,
route handlers, sync endpoints, and other uncovered branches.

Extends the existing test file with additional coverage for uncovered lines.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes
from app.fastapi_routes.xcmax_admin import (
    CORE_MODULES,
    REMOTE_HOST,
    REMOTE_PORT,
    _collect_employee_pack_modules,
    _collect_mod_modules,
    _inject_digest_api_base,
    _probe_remote_health_sync,
    _release_train_snapshot,
    _require_market_admin_session,
    router,
)


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _require_market_admin_session
# ---------------------------------------------------------------------------


class TestRequireMarketAdminSession:
    """Tests for _require_market_admin_session."""

    def test_no_session_id_returns_401(self):
        """When no session ID, should return 401."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            result = _require_market_admin_session(req)
            assert result is not None
            assert result.status_code == 401

    def test_non_admin_returns_403(self):
        """When session is not admin, should return 403."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "user", "market_is_admin": False},
        ):
            result = _require_market_admin_session(req)
            assert result is not None
            assert result.status_code == 403

    def test_admin_returns_none(self):
        """When session is admin, should return None (no gate)."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ):
            result = _require_market_admin_session(req)
            assert result is None

    def test_admin_kind_but_not_market_admin_returns_403(self):
        """When account_kind is admin but market_is_admin is False, should return 403."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": False},
        ):
            result = _require_market_admin_session(req)
            assert result is not None
            assert result.status_code == 403

    def test_no_meta_returns_403(self):
        """When load_session_account_meta returns None, should return 403."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value=None,
        ):
            result = _require_market_admin_session(req)
            assert result is not None
            assert result.status_code == 403


# ---------------------------------------------------------------------------
# _release_train_snapshot — additional edge cases
# ---------------------------------------------------------------------------


class TestReleaseTrainSnapshotEdgeCases:
    """Additional edge cases for _release_train_snapshot."""

    def test_with_valid_json_file(self, tmp_path):
        """Should read and return JSON from file."""
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        test_data = {
            "epoch": "2.0.0.0",
            "current": "2.0.0.0",
            "started_at": "2026-06-01",
            "day_index": 15,
        }
        (cfg_dir / "release_train.json").write_text(
            json.dumps(test_data), encoding="utf-8"
        )
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            result = _release_train_snapshot()
            assert result["epoch"] == "2.0.0.0"
            assert result["day_index"] == 15

    def test_with_invalid_json_file(self, tmp_path):
        """Should return defaults when JSON is invalid."""
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text("not valid json{{{")
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            result = _release_train_snapshot()
            assert "epoch" in result

    def test_with_non_dict_json(self, tmp_path):
        """Should return defaults when JSON is not a dict."""
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text(json.dumps([1, 2, 3]))
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            result = _release_train_snapshot()
            assert "epoch" in result


# ---------------------------------------------------------------------------
# _collect_mod_modules
# ---------------------------------------------------------------------------


class TestCollectModModules:
    """Tests for _collect_mod_modules."""

    def test_no_mod_manager(self):
        """When get_mod_manager returns None, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            result = _collect_mod_modules()
            assert result == []

    def test_with_mods(self):
        """When mod_manager has mods, should return formatted list."""
        mock_meta1 = MagicMock()
        mock_meta1.name = "TestMod"
        mock_meta1.version = "1.0"

        mock_meta2 = MagicMock()
        mock_meta2.name = "AnotherMod"
        mock_meta2.version = "2.0"

        mock_mgr = MagicMock()
        mock_mgr._registry = {"test_mod": mock_meta1, "another": mock_meta2}

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            result = _collect_mod_modules()
            assert len(result) == 2
            assert result[0]["module_id"] == "test_mod"
            assert result[0]["source"] == "local"
            assert result[0]["route"] == "/mod/test_mod"
            assert result[1]["module_id"] == "another"

    def test_with_empty_registry(self):
        """When registry is empty, should return empty list."""
        mock_mgr = MagicMock()
        mock_mgr._registry = {}

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            result = _collect_mod_modules()
            assert result == []

    def test_import_error_returns_empty(self):
        """When import fails, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("no module"),
        ):
            result = _collect_mod_modules()
            assert result == []

    def test_mod_without_name_uses_id(self):
        """When mod has no name, should use mod_id as display_name."""
        mock_meta = MagicMock()
        mock_meta.name = None
        mock_meta.version = ""

        mock_mgr = MagicMock()
        mock_mgr._registry = {"my_mod": mock_meta}

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            result = _collect_mod_modules()
            assert result[0]["display_name"] == "my_mod"


# ---------------------------------------------------------------------------
# _collect_employee_pack_modules
# ---------------------------------------------------------------------------


class TestCollectEmployeePackModules:
    """Tests for _collect_employee_pack_modules."""

    def test_no_mod_manager(self):
        """When get_mod_manager returns None, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            result = _collect_employee_pack_modules()
            assert result == []

    def test_with_employee_packs(self):
        """When employee packs exist, should return formatted list."""
        mock_mgr = MagicMock()
        mock_mgr.mods_root = "/tmp/mods"

        mock_registry = MagicMock()
        mock_registry.list_packs.return_value = [
            {"id": "emp1", "name": "Employee 1", "version": "1.0"},
            {"id": "emp2", "name": "Employee 2", "version": "2.0"},
        ]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ), patch(
            "app.infrastructure.mods.employee_registry.EmployeeRegistry",
            return_value=mock_registry,
        ):
            result = _collect_employee_pack_modules()
            assert len(result) == 2
            assert result[0]["module_id"] == "emp1"
            assert result[0]["source"] == "employee"
            assert result[0]["display_name"] == "Employee 1"

    def test_employee_pack_without_name(self):
        """When pack has no name, should use pack_id."""
        mock_mgr = MagicMock()
        mock_mgr.mods_root = "/tmp/mods"

        mock_registry = MagicMock()
        mock_registry.list_packs.return_value = [
            {"id": "emp1", "version": "1.0"},
        ]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ), patch(
            "app.infrastructure.mods.employee_registry.EmployeeRegistry",
            return_value=mock_registry,
        ):
            result = _collect_employee_pack_modules()
            assert result[0]["display_name"] == "emp1"

    def test_import_error_returns_empty(self):
        """When import fails, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("no module"),
        ):
            result = _collect_employee_pack_modules()
            assert result == []


# ---------------------------------------------------------------------------
# _inject_digest_api_base
# ---------------------------------------------------------------------------


class TestInjectDigestApiBase:
    """Tests for _inject_digest_api_base."""

    def test_injects_base_into_data(self):
        """Should inject digest_api_base into data dict."""
        payload = {"success": True, "data": {"key": "value"}}
        result = _inject_digest_api_base(payload, "https://api.example.com")
        assert result["data"]["digest_api_base"] == "https://api.example.com"

    def test_no_data_key(self):
        """When payload has no 'data' key, should return unchanged."""
        payload = {"success": True}
        result = _inject_digest_api_base(payload, "https://api.example.com")
        assert "digest_api_base" not in result

    def test_data_not_dict(self):
        """When data is not a dict, should return unchanged."""
        payload = {"success": True, "data": "not a dict"}
        result = _inject_digest_api_base(payload, "https://api.example.com")
        assert result["data"] == "not a dict"

    def test_empty_base(self):
        """Empty base string should still be injected."""
        payload = {"success": True, "data": {}}
        result = _inject_digest_api_base(payload, "")
        assert result["data"]["digest_api_base"] == ""


# ---------------------------------------------------------------------------
# _probe_remote_health_sync
# ---------------------------------------------------------------------------


class TestProbeRemoteHealthSync:
    """Tests for _probe_remote_health_sync."""

    def test_successful_probe(self):
        """Should return success with latency when remote is reachable."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"version": "1.0.0", "timestamp": "2026-06-16T00:00:00"}
        ).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _probe_remote_health_sync()
            assert result["success"] is True
            assert result["data"]["reachable"] is True
            assert result["data"]["latency_ms"] is not None
            assert result["data"]["version"] == "1.0.0"

    def test_failed_probe(self):
        """Should return unreachable when remote is not reachable."""
        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionError("connection refused"),
        ):
            result = _probe_remote_health_sync()
            assert result["success"] is True
            assert result["data"]["reachable"] is False
            assert result["data"]["error"] is not None

    def test_timeout_probe(self):
        """Should return unreachable when remote times out."""
        with patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            result = _probe_remote_health_sync()
            assert result["data"]["reachable"] is False

    def test_probe_returns_host_and_port(self):
        """Should include host and port in result."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"version": "1.0"}).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _probe_remote_health_sync()
            assert result["data"]["host"] == REMOTE_HOST
            assert result["data"]["port"] == REMOTE_PORT


# ---------------------------------------------------------------------------
# CORE_MODULES
# ---------------------------------------------------------------------------


class TestCoreModules:
    """Tests for CORE_MODULES constant."""

    def test_core_modules_not_empty(self):
        assert len(CORE_MODULES) > 0

    def test_core_modules_have_required_keys(self):
        for mod in CORE_MODULES:
            assert "module_id" in mod
            assert "display_name" in mod
            assert "route" in mod
            assert "source" in mod
            assert "sync_scope" in mod
            assert "active" in mod
            assert "version" in mod

    def test_all_core_modules_active(self):
        for mod in CORE_MODULES:
            assert mod["active"] is True

    def test_all_core_modules_source_core(self):
        for mod in CORE_MODULES:
            assert mod["source"] == "core"


# ---------------------------------------------------------------------------
# Route handlers — using TestClient
# ---------------------------------------------------------------------------


class TestListModulesRoute:
    """Tests for GET /api/xcmax/admin/modules."""

    def test_list_modules_returns_modules(self, client: TestClient):
        """Should return core + mod + employee modules."""
        with patch(
            "app.fastapi_routes.xcmax_admin._collect_mod_modules",
            return_value=[],
        ), patch(
            "app.fastapi_routes.xcmax_admin._collect_employee_pack_modules",
            return_value=[],
        ):
            response = client.get("/api/xcmax/admin/modules")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["total"] == len(CORE_MODULES)
            assert len(data["data"]) == len(CORE_MODULES)

    def test_list_modules_includes_mods(self, client: TestClient):
        """Should include mod modules in response."""
        mock_mod = {
            "module_id": "test_mod",
            "display_name": "Test Mod",
            "route": "/mod/test_mod",
            "source": "local",
            "sync_scope": "module_info",
            "active": True,
            "version": "1.0",
        }

        with patch(
            "app.fastapi_routes.xcmax_admin._collect_mod_modules",
            return_value=[mock_mod],
        ), patch(
            "app.fastapi_routes.xcmax_admin._collect_employee_pack_modules",
            return_value=[],
        ):
            response = client.get("/api/xcmax/admin/modules")
            data = response.json()
            assert data["total"] == len(CORE_MODULES) + 1
            mod_ids = [m["module_id"] for m in data["data"]]
            assert "test_mod" in mod_ids


class TestReleaseTrainRoute:
    """Tests for GET /api/xcmax/release-train."""

    def test_release_train_returns_snapshot(self, client: TestClient):
        """Should return release train snapshot."""
        with patch(
            "app.fastapi_routes.xcmax_admin._release_train_snapshot",
            return_value={"epoch": "2.0.0.0", "current": "2.0.0.0"},
        ):
            response = client.get("/api/xcmax/release-train")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True


class TestRemoteStatusRoute:
    """Tests for GET /api/xcmax/admin/remote-status."""

    def test_remote_status_returns_result(self, client: TestClient):
        """Should return remote status."""
        with patch(
            "app.fastapi_routes.xcmax_admin._probe_remote_health_sync",
            return_value={
                "success": True,
                "data": {"reachable": False, "latency_ms": None, "error": "timeout"},
            },
        ):
            response = client.get("/api/xcmax/admin/remote-status")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True


# ---------------------------------------------------------------------------
# Sync routes
# ---------------------------------------------------------------------------


class TestSyncStatusRoute:
    """Tests for GET /api/xcmax/sync/status."""

    def test_sync_status_returns_data(self, client: TestClient):
        """Should return sync status."""
        mock_db = MagicMock()
        mock_db.get_status.return_value = {
            "healthy": True,
            "local_cursor": 1,
            "remote_cursor": 1,
            "outbox_count": 0,
            "last_sync_at": "2026-06-16",
            "conflict_count": 0,
        }
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            response = client.get("/api/xcmax/sync/status")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_sync_status_db_unavailable(self, client: TestClient):
        """Should return fallback when SyncDb is unavailable."""
        with patch("app.db.xcmax_sync.SyncDb", side_effect=ImportError("no module")):
            response = client.get("/api/xcmax/sync/status")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["healthy"] is False


class TestSyncChangesRoute:
    """Tests for GET /api/xcmax/sync/changes."""

    def test_sync_changes_returns_data(self, client: TestClient):
        """Should return changes list."""
        mock_db = MagicMock()
        mock_db.get_changes.return_value = [
            {"id": 1, "entity_type": "product", "action": "update"},
        ]
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            response = client.get("/api/xcmax/sync/changes?since_cursor=0&limit=100")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["count"] == 1

    def test_sync_changes_db_unavailable(self, client: TestClient):
        """Should return empty list when SyncDb is unavailable."""
        with patch("app.db.xcmax_sync.SyncDb", side_effect=ImportError("no module")):
            response = client.get("/api/xcmax/sync/changes")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0


class TestSyncPushRoute:
    """Tests for POST /api/xcmax/sync/push."""

    def test_sync_push_success(self, client: TestClient):
        """Should return push result."""
        with patch(
            "app.application.xcmax_sync_app.push_outbox",
            return_value={"pushed": 5},
        ):
            response = client.post("/api/xcmax/sync/push")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_sync_push_failure(self, client: TestClient):
        """Should return 500 when push fails."""
        with patch(
            "app.application.xcmax_sync_app.push_outbox",
            side_effect=RuntimeError("connection failed"),
        ):
            response = client.post("/api/xcmax/sync/push")
            assert response.status_code == 500


class TestSyncReceiveRoute:
    """Tests for POST /api/xcmax/sync/receive."""

    def test_sync_receive_single_item(self):
        """Should receive and apply a single item."""
        mock_db = MagicMock()
        mock_db.enqueue_inbox.return_value = 1
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 1},
            ),
            patch("app.mod_sdk.audit.write_audit_event"),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                admin_routes.sync_receive({"entity_type": "product", "action": "create"})
            )
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["received"] == 1

    def test_sync_receive_list_items(self):
        """Should receive and apply a list of items."""
        mock_db = MagicMock()
        mock_db.enqueue_inbox.return_value = 2
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 2},
            ),
            patch("app.mod_sdk.audit.write_audit_event"),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                admin_routes.sync_receive([
                    {"entity_type": "product", "action": "create"},
                    {"entity_type": "order", "action": "update"},
                ])
            )
            assert result["received"] == 2


class TestSyncConflictsRoute:
    """Tests for GET /api/xcmax/sync/conflicts."""

    def test_list_conflicts(self, client: TestClient):
        """Should return conflicts list."""
        with patch(
            "app.services.admin_sync_service.list_sync_conflicts",
            return_value=[{"id": 1, "entity_type": "product"}],
        ):
            response = client.get("/api/xcmax/sync/conflicts")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["count"] == 1

    def test_list_conflicts_unavailable(self, client: TestClient):
        """Should return empty list when service is unavailable."""
        with patch(
            "app.services.admin_sync_service.list_sync_conflicts",
            side_effect=ImportError("no module"),
        ):
            response = client.get("/api/xcmax/sync/conflicts")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0


class TestResolveConflictRoute:
    """Tests for POST /api/xcmax/sync/conflicts/{inbox_id}/resolve."""

    def test_resolve_conflict_apply(self, client: TestClient):
        """Should apply conflict resolution."""
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.fetch_inbox_row",
                return_value={"entity_type": "product", "payload": "{}"},
            ),
            patch(
                "app.application.xcmax_sync_app.entity_appliers",
                return_value={},
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "apply"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["action"] == "apply"

    def test_resolve_conflict_skip(self, client: TestClient):
        """Should skip conflict resolution."""
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.mark_inbox_skipped",
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "skip"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["action"] == "skip"


# ---------------------------------------------------------------------------
# Local employee routes
# ---------------------------------------------------------------------------


class TestLocalEmployeeRoutes:
    """Tests for local employee routes."""

    def test_local_employee_status_no_session(self, client: TestClient):
        """Should return 401 when no session."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/status")
            assert response.status_code == 401

    def test_local_employee_manifest_no_session(self, client: TestClient):
        """Should return 401 when no session."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
            assert response.status_code == 401

    def test_local_employee_status_empty_id(self, client: TestClient):
        """Should return 400 when employee_id is empty."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ):
            response = client.get("/api/xcmax/local/employees/%20/status")
            assert response.status_code == 400

    def test_local_employee_manifest_not_found(self, client: TestClient):
        """Should return 404 when manifest not found."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
            assert response.status_code == 404

    def test_local_employee_manifest_found(self, client: TestClient):
        """Should return manifest when found."""
        mock_manifest = {"id": "emp1", "name": "Employee 1"}
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=mock_manifest,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
            assert response.status_code == 200


class TestLocalDutyGraphHealthRoute:
    """Tests for GET /api/xcmax/local/duty-graph/health."""

    def test_no_session_returns_401(self, client: TestClient):
        """Should return 401 when no session."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/duty-graph/health")
            assert response.status_code == 401

    def test_with_session_returns_health(self, client: TestClient):
        """Should return health data when session exists."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.local_duty_graph_health.build_local_duty_graph_health",
            return_value={"healthy": True},
        ):
            response = client.get("/api/xcmax/local/duty-graph/health")
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Ops routes
# ---------------------------------------------------------------------------


class TestOpsRoutes:
    """Tests for ops routes."""

    def test_ops_job_detail_invalid_id(self, client: TestClient):
        """Should return error when job_id is invalid."""
        response = client.get("/api/xcmax/ops/jobs/")
        assert response.status_code in (400, 401, 404, 422)

    def test_ops_duty_run_detail_invalid_id(self, client: TestClient):
        """Should return 400 when run_id is invalid."""
        response = client.get("/api/xcmax/ops/duty-runs/0")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# _market_admin_proxy — edge cases
# ---------------------------------------------------------------------------


class TestMarketAdminProxyEdgeCases:
    """Tests for _market_admin_proxy edge cases."""

    @pytest.mark.asyncio
    async def test_import_error_returns_500(self):
        """When market_account import fails, should return 500."""
        req = MagicMock(spec=Request)

        with patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=None,
        ), patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": None},
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
            # Should handle import error gracefully
            assert result is not None
            if isinstance(result, JSONResponse):
                assert result.status_code == 500


# ---------------------------------------------------------------------------
# WeChat group routes
# ---------------------------------------------------------------------------


class TestWeChatGroupRoutes:
    """Tests for WeChat group admin routes."""

    def test_list_wechat_groups_no_session(self, client: TestClient):
        """Should return 401 when no admin session."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/admin/wechat/groups")
            assert response.status_code == 401

    def test_list_wechat_groups_with_session(self, client: TestClient):
        """Should return groups when admin session exists."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ), patch(
            "app.services.wechat_group_customer_bridge.list_group_contacts",
            return_value=[{"id": 1, "name": "Group1"}],
        ):
            response = client.get("/api/xcmax/admin/wechat/groups")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["total"] == 1


# ---------------------------------------------------------------------------
# Impersonate routes
# ---------------------------------------------------------------------------


class TestImpersonateRoutes:
    """Tests for impersonate routes."""

    def test_impersonate_no_session(self, client: TestClient):
        """Should return 401 when no admin session."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.post("/api/xcmax/admin/impersonate", json={"market_user_id": 1})
            assert response.status_code == 401

    def test_impersonate_no_user_id(self, client: TestClient):
        """Should return 400 when market_user_id is missing."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ):
            response = client.post("/api/xcmax/admin/impersonate", json={})
            assert response.status_code == 400

    def test_impersonate_invalid_user_id(self, client: TestClient):
        """Should return 400 when market_user_id is not a number."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ), patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ):
            response = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": "not_a_number"},
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# Sync pull route
# ---------------------------------------------------------------------------


class TestSyncPullRoute:
    """Tests for POST /api/xcmax/sync/pull."""

    def test_sync_pull_success(self, client: TestClient):
        """Should return pull and apply results."""
        with patch(
            "app.application.xcmax_sync_app.pull_from_remote",
            return_value={"pulled": 3},
        ), patch(
            "app.application.xcmax_sync_app.apply_inbox",
            return_value={"applied": 3},
        ):
            response = client.post("/api/xcmax/sync/pull")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "pull" in data["data"]
            assert "apply" in data["data"]

    def test_sync_pull_failure(self, client: TestClient):
        """Should return 500 when pull fails."""
        with patch(
            "app.application.xcmax_sync_app.pull_from_remote",
            side_effect=RuntimeError("connection failed"),
        ):
            response = client.post("/api/xcmax/sync/pull")
            assert response.status_code == 500
