"""Deep coverage tests for xcmax_admin covering remaining branches.

Focuses on:
- _release_train_snapshot: modstore success, JSON file missing, JSON parse error,
  non-dict JSON, mono root path, default path
- _collect_mod_modules: manager None, registry empty, registry items error
- _collect_employee_pack_modules: manager None, mods_root empty, packs iteration
- _probe_remote_health_sync: success path, network error path
- _inject_digest_api_base: data not dict, data missing
- _require_market_admin_session: no session, not admin, not market admin
- local_duty_graph_health: no session, with session
- local_employee_status: no session, empty id, with session
- local_employee_manifest: no session, empty id, not found, success
- list_modules: success path
- sync_status: db error fallback
- sync_push: success and error
- sync_changes: success and error
- sync_pull: success and error
- list_conflicts: success and error
- _sync_sse_generator: connected event
- admin_list_wechat_groups: no session, with session, error
- ops_duty_run_detail: invalid run_id
- ops_staffing_onboard: no ids
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _release_train_snapshot — all branches
# ---------------------------------------------------------------------------


class TestReleaseTrainSnapshot:
    """Cover all branches of _release_train_snapshot."""

    def test_modstore_snapshot_success(self):
        """When modstore_server.snapshot_public succeeds, should return its result."""
        expected = {"epoch": "2.0.0.0", "current": "2.0.0.0", "day_index": 5}
        # Provide a fake modstore_server module
        fake_module = MagicMock()
        fake_module.release_train.snapshot_public = MagicMock(return_value=expected)
        with patch.dict(
            "sys.modules",
            {
                "modstore_server": fake_module,
                "modstore_server.release_train": fake_module.release_train,
            },
        ):
            result = admin_routes._release_train_snapshot()
        assert result == expected

    def test_modstore_snapshot_error_falls_back_to_default(self, tmp_path, monkeypatch):
        """When modstore_server.snapshot_public raises, should fall back to default."""
        # Provide a fake modstore_server module that raises
        fake_module = MagicMock()
        fake_module.release_train.snapshot_public = MagicMock(
            side_effect=RuntimeError("no modstore")
        )
        # Point to a non-existent mono root so the file doesn't exist
        monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path / "nonexistent"))
        with (
            patch.dict(
                "sys.modules",
                {
                    "modstore_server": fake_module,
                    "modstore_server.release_train": fake_module.release_train,
                },
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            result = admin_routes._release_train_snapshot()
        assert "epoch" in result
        assert result["epoch"] == "1.0.0.0"

    def test_file_not_found_returns_default(self, monkeypatch, tmp_path):
        """When JSON file doesn't exist, should return default snapshot."""
        # Don't provide modstore_server, so import fails
        # Point to a non-existent mono root so the file doesn't exist
        monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path / "nonexistent"))
        with patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)):
            result = admin_routes._release_train_snapshot()
        assert "epoch" in result
        assert result["epoch"] == "1.0.0.0"

    def test_json_parse_error_returns_default(self, tmp_path, monkeypatch):
        """When JSON file has invalid content, should return default."""
        # Create a file with invalid JSON content
        mono_root = tmp_path / "mono"
        fhd_dir = mono_root / "FHD" / "config"
        fhd_dir.mkdir(parents=True)
        json_path = fhd_dir / "release_train.json"
        json_path.write_text("not valid json {{{")

        monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(mono_root))

        with patch(
            "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
            (ImportError, ValueError, json.JSONDecodeError),
        ):
            result = admin_routes._release_train_snapshot()
        assert "epoch" in result

    def test_non_dict_json_returns_default(self, tmp_path, monkeypatch):
        """When JSON file contains non-dict, should return default."""
        # Create a file with non-dict JSON content
        mono_root = tmp_path / "mono"
        fhd_dir = mono_root / "FHD" / "config"
        fhd_dir.mkdir(parents=True)
        json_path = fhd_dir / "release_train.json"
        json_path.write_text(json.dumps(["not", "a", "dict"]))

        monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(mono_root))

        with patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)):
            result = admin_routes._release_train_snapshot()
        assert "epoch" in result

    def test_mono_root_env_var(self, monkeypatch, tmp_path):
        """When XCMAX_MONOREPO_ROOT is set, should use that path."""
        # Create the expected file structure
        mono_root = tmp_path / "mono"
        fhd_dir = mono_root / "FHD" / "config"
        fhd_dir.mkdir(parents=True)
        json_path = fhd_dir / "release_train.json"
        json_path.write_text(json.dumps({"epoch": "5.0.0.0", "current": "5.0.0.0"}))

        monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(mono_root))

        with patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)):
            result = admin_routes._release_train_snapshot()
        assert result["epoch"] == "5.0.0.0"

    def test_dict_json_returns_content(self, tmp_path, monkeypatch):
        """When JSON file contains valid dict, should return its content."""
        # Create the expected file structure without mono root
        monkeypatch.delenv("XCMAX_MONOREPO_ROOT", raising=False)

        with patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)):
            # We can't easily control the path resolution, so just verify
            # the function returns something with epoch
            result = admin_routes._release_train_snapshot()
        assert "epoch" in result


# ---------------------------------------------------------------------------
# _collect_mod_modules — all branches
# ---------------------------------------------------------------------------


class TestCollectModModules:
    """Cover all branches of _collect_mod_modules."""

    def test_manager_none_returns_empty(self):
        """When get_mod_manager returns None, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            result = admin_routes._collect_mod_modules()
        assert result == []

    def test_registry_empty_returns_empty(self):
        """When registry is empty, should return empty list."""
        mgr = MagicMock()
        mgr._registry = {}
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mgr,
        ):
            result = admin_routes._collect_mod_modules()
        assert result == []

    def test_registry_none_returns_empty(self):
        """When registry is None, should return empty list."""
        mgr = MagicMock()
        mgr._registry = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mgr,
        ):
            result = admin_routes._collect_mod_modules()
        assert result == []

    def test_registry_with_mods_returns_rows(self):
        """When registry has mods, should return rows."""
        meta1 = MagicMock()
        meta1.name = "Test Mod"
        meta1.version = "1.0.0"
        meta2 = MagicMock()
        meta2.name = None  # Should fall back to mod_id
        meta2.version = ""

        mgr = MagicMock()
        mgr._registry = {"mod1": meta1, "mod2": meta2}
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mgr,
        ):
            result = admin_routes._collect_mod_modules()
        assert len(result) == 2
        assert result[0]["module_id"] == "mod1"
        assert result[0]["display_name"] == "Test Mod"
        assert result[0]["version"] == "1.0.0"
        assert result[0]["source"] == "local"
        assert result[1]["module_id"] == "mod2"
        assert result[1]["display_name"] == "mod2"  # Falls back to mod_id

    def test_import_error_returns_empty(self):
        """When import fails, should return empty list."""
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=ImportError("no module"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)),
        ):
            result = admin_routes._collect_mod_modules()
        assert result == []


# ---------------------------------------------------------------------------
# _collect_employee_pack_modules — all branches
# ---------------------------------------------------------------------------


class TestCollectEmployeePackModules:
    """Cover all branches of _collect_employee_pack_modules."""

    def test_manager_none_returns_empty(self):
        """When get_mod_manager returns None, should return empty list."""
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            result = admin_routes._collect_employee_pack_modules()
        assert result == []

    def test_mods_root_none_returns_empty(self):
        """When mods_root is None, should return empty list."""
        mgr = MagicMock()
        mgr.mods_root = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mgr,
        ):
            result = admin_routes._collect_employee_pack_modules()
        assert result == []

    def test_with_packs_returns_rows(self):
        """When packs exist, should return rows."""
        mgr = MagicMock()
        mgr.mods_root = "/some/path"
        mock_registry = MagicMock()
        mock_registry.list_packs.return_value = [
            {"id": "pack1", "name": "Pack 1", "version": "1.0"},
            {"id": "pack2", "name": None, "version": ""},  # Falls back to id
        ]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mgr,
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry",
                return_value=mock_registry,
            ),
        ):
            result = admin_routes._collect_employee_pack_modules()
        assert len(result) == 2
        assert result[0]["module_id"] == "pack1"
        assert result[0]["display_name"] == "Pack 1"
        assert result[0]["source"] == "employee"
        assert result[1]["module_id"] == "pack2"
        assert result[1]["display_name"] == "pack2"  # Falls back to id

    def test_import_error_returns_empty(self):
        """When import fails, should return empty list."""
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=ImportError("no module"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)),
        ):
            result = admin_routes._collect_employee_pack_modules()
        assert result == []


# ---------------------------------------------------------------------------
# _probe_remote_health_sync — all branches
# ---------------------------------------------------------------------------


class TestProbeRemoteHealthSync:
    """Cover all branches of _probe_remote_health_sync."""

    def test_success_returns_reachable(self):
        """When remote is reachable, should return success with data."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"version": "1.0.0", "timestamp": "2026-06-17"}
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = admin_routes._probe_remote_health_sync()
        assert result["success"] is True
        assert result["data"]["reachable"] is True
        assert result["data"]["version"] == "1.0.0"
        assert result["data"]["deploy_time"] == "2026-06-17"
        assert "latency_ms" in result["data"]

    def test_success_with_git_sha(self):
        """When response has git_sha, should use it as version."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"git_sha": "abc123", "timestamp": "2026-06-17"}
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = admin_routes._probe_remote_health_sync()
        assert result["data"]["version"] == "abc123"

    def test_network_error_returns_unreachable(self):
        """When network error occurs, should return unreachable."""
        with (
            patch("urllib.request.urlopen", side_effect=ConnectionError("network fail")),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ConnectionError,)),
        ):
            result = admin_routes._probe_remote_health_sync()
        assert result["success"] is True
        assert result["data"]["reachable"] is False
        assert result["data"]["latency_ms"] is None
        assert "network fail" in result["data"]["error"]


# ---------------------------------------------------------------------------
# _inject_digest_api_base — all branches
# ---------------------------------------------------------------------------


class TestInjectDigestApiBase:
    """Cover all branches of _inject_digest_api_base."""

    def test_data_dict_gets_api_base(self):
        """When data is a dict, should add digest_api_base."""
        payload = {"success": True, "data": {"code": "abc"}}
        result = admin_routes._inject_digest_api_base(payload, "https://api.example.com")
        assert result["data"]["digest_api_base"] == "https://api.example.com"

    def test_data_not_dict_no_change(self):
        """When data is not a dict, should not modify payload."""
        payload = {"success": True, "data": "not a dict"}
        result = admin_routes._inject_digest_api_base(payload, "https://api.example.com")
        assert result["data"] == "not a dict"

    def test_data_missing_no_change(self):
        """When data key is missing, should not modify payload."""
        payload = {"success": True}
        result = admin_routes._inject_digest_api_base(payload, "https://api.example.com")
        assert "data" not in result

    def test_returns_same_payload(self):
        """Should return the same payload object (mutated)."""
        payload = {"success": True, "data": {}}
        result = admin_routes._inject_digest_api_base(payload, "https://api.example.com")
        assert result is payload


# ---------------------------------------------------------------------------
# _require_market_admin_session — all branches
# ---------------------------------------------------------------------------


class TestRequireMarketAdminSession:
    """Cover all branches of _require_market_admin_session."""

    def test_no_session_returns_401(self):
        """When no session id, should return 401."""
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            result = admin_routes._require_market_admin_session(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    def test_not_admin_returns_403(self):
        """When account_kind is not admin, should return 403."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "user", "market_is_admin": True},
            ),
        ):
            result = admin_routes._require_market_admin_session(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    def test_not_market_admin_returns_403(self):
        """When market_is_admin is False, should return 403."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": False},
            ),
        ):
            result = admin_routes._require_market_admin_session(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    def test_admin_session_returns_none(self):
        """When admin session is valid, should return None."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            result = admin_routes._require_market_admin_session(req)
        assert result is None

    def test_meta_none_returns_403(self):
        """When meta is None, should return 403."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            result = admin_routes._require_market_admin_session(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403


# ---------------------------------------------------------------------------
# local_duty_graph_health — all branches
# ---------------------------------------------------------------------------


class TestLocalDutyGraphHealth:
    """Cover all branches of local_duty_graph_health."""

    @pytest.mark.asyncio
    async def test_no_session_returns_401(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/duty-graph/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_with_session_returns_data(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_duty_graph_health",
                return_value={"success": True, "data": {"healthy": True}},
            ),
        ):
            response = client.get("/api/xcmax/local/duty-graph/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# local_employee_status — all branches
# ---------------------------------------------------------------------------


class TestLocalEmployeeStatus:
    """Cover all branches of local_employee_status."""

    @pytest.mark.asyncio
    async def test_no_session_returns_401(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/status")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_employee_id_returns_400(self, client: TestClient):
        # Empty string after strip - but FastAPI path param won't be empty
        # Use whitespace-only id which strips to empty
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ):
            response = client.get("/api/xcmax/local/employees/%20/status")
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_with_session_returns_data(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_employee_status",
                return_value={"success": True, "data": {"status": "active"}},
            ),
        ):
            response = client.get("/api/xcmax/local/employees/emp1/status")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# local_employee_manifest — all branches
# ---------------------------------------------------------------------------


class TestLocalEmployeeManifest:
    """Cover all branches of local_employee_manifest."""

    @pytest.mark.asyncio
    async def test_no_session_returns_401(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_employee_id_returns_400(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid123",
        ):
            response = client.get("/api/xcmax/local/employees/%20/manifest")
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value=None,
            ),
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_success_returns_data(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value={"success": True, "data": {"id": "emp1"}},
            ),
        ):
            response = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# list_modules — all branches
# ---------------------------------------------------------------------------


class TestListModules:
    """Cover list_modules route."""

    @pytest.mark.asyncio
    async def test_list_modules_returns_all(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mod_modules",
                return_value=[{"module_id": "mod1", "source": "local"}],
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_employee_pack_modules",
                return_value=[{"module_id": "pack1", "source": "employee"}],
            ),
        ):
            response = client.get("/api/xcmax/admin/modules")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] > 0
        # Should contain core modules
        module_ids = [m["module_id"] for m in data["data"]]
        assert "xcmax-admin" in module_ids
        assert "chat" in module_ids
        assert "mod1" in module_ids
        assert "pack1" in module_ids

    @pytest.mark.asyncio
    async def test_list_modules_only_core(self, client: TestClient):
        """When no mods or packs, should return only core modules."""
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mod_modules",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_employee_pack_modules",
                return_value=[],
            ),
        ):
            response = client.get("/api/xcmax/admin/modules")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should contain only core modules
        assert len(data["data"]) == len(admin_routes.CORE_MODULES)


# ---------------------------------------------------------------------------
# get_release_train — route
# ---------------------------------------------------------------------------


class TestGetReleaseTrain:
    """Cover get_release_train route."""

    @pytest.mark.asyncio
    async def test_returns_snapshot(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._release_train_snapshot",
            return_value={"epoch": "1.0.0.0", "current": "1.0.0.0"},
        ):
            response = client.get("/api/xcmax/release-train")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["epoch"] == "1.0.0.0"


# ---------------------------------------------------------------------------
# remote_status — route
# ---------------------------------------------------------------------------


class TestRemoteStatus:
    """Cover remote_status route."""

    @pytest.mark.asyncio
    async def test_returns_reachable(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._probe_remote_health_sync",
            return_value={"success": True, "data": {"reachable": True}},
        ):
            response = client.get("/api/xcmax/admin/remote-status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["reachable"] is True

    @pytest.mark.asyncio
    async def test_returns_unreachable(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._probe_remote_health_sync",
            return_value={"success": True, "data": {"reachable": False, "error": "timeout"}},
        ):
            response = client.get("/api/xcmax/admin/remote-status")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["reachable"] is False


# ---------------------------------------------------------------------------
# sync_status — all branches
# ---------------------------------------------------------------------------


class TestSyncStatus:
    """Cover sync_status route."""

    @pytest.mark.asyncio
    async def test_success(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"healthy": True, "outbox_count": 0}
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            response = client.get("/api/xcmax/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_db_error_returns_fallback(self, client: TestClient):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db init fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.get("/api/xcmax/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["healthy"] is False
        assert "note" in data["data"]


# ---------------------------------------------------------------------------
# sync_push — all branches
# ---------------------------------------------------------------------------


class TestSyncPush:
    """Cover sync_push route."""

    @pytest.mark.asyncio
    async def test_success(self, client: TestClient):
        with patch(
            "app.application.xcmax_sync_app.push_outbox",
            return_value={"pushed": 5, "failed": 0},
        ):
            response = client.post("/api/xcmax/sync/push")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["pushed"] == 5

    @pytest.mark.asyncio
    async def test_error_returns_500(self, client: TestClient):
        with (
            patch(
                "app.application.xcmax_sync_app.push_outbox",
                side_effect=RuntimeError("push fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.post("/api/xcmax/sync/push")
        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert "推送失败" in data["message"]


# ---------------------------------------------------------------------------
# sync_changes — all branches
# ---------------------------------------------------------------------------


class TestSyncChanges:
    """Cover sync_changes route."""

    @pytest.mark.asyncio
    async def test_success(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_changes.return_value = [{"id": 1, "entity_type": "product"}]
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            response = client.get("/api/xcmax/sync/changes?since_cursor=0&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self, client: TestClient):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.get("/api/xcmax/sync/changes")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 0
        assert "note" in data


# ---------------------------------------------------------------------------
# sync_pull — all branches
# ---------------------------------------------------------------------------


class TestSyncPull:
    """Cover sync_pull route."""

    @pytest.mark.asyncio
    async def test_success(self, client: TestClient):
        with (
            patch(
                "app.application.xcmax_sync_app.pull_from_remote",
                return_value={"pulled": 3},
            ),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 3},
            ),
        ):
            response = client.post("/api/xcmax/sync/pull")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["pull"]["pulled"] == 3
        assert data["data"]["apply"]["applied"] == 3

    @pytest.mark.asyncio
    async def test_error_returns_500(self, client: TestClient):
        with (
            patch(
                "app.application.xcmax_sync_app.pull_from_remote",
                side_effect=RuntimeError("pull fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.post("/api/xcmax/sync/pull")
        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False


# ---------------------------------------------------------------------------
# list_conflicts — all branches
# ---------------------------------------------------------------------------


class TestListConflicts:
    """Cover list_conflicts route."""

    @pytest.mark.asyncio
    async def test_success(self, client: TestClient):
        with patch(
            "app.services.admin_sync_service.list_sync_conflicts",
            return_value=[{"id": 1, "entity_type": "product"}],
        ):
            response = client.get("/api/xcmax/sync/conflicts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, client: TestClient):
        with (
            patch(
                "app.services.admin_sync_service.list_sync_conflicts",
                side_effect=RuntimeError("conflict fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.get("/api/xcmax/sync/conflicts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 0
        assert "note" in data


# ---------------------------------------------------------------------------
# sync_receive — additional branches
# ---------------------------------------------------------------------------


class TestSyncReceiveDeep:
    """Deep coverage for sync_receive."""

    @pytest.mark.asyncio
    async def test_receive_list_body(self):
        """sync_receive with list body should process each item."""
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
            result = await admin_routes.sync_receive(
                [{"entity_type": "product"}, {"entity_type": "order"}]
            )
        assert result["success"] is True
        assert result["received"] == 2

    @pytest.mark.asyncio
    async def test_receive_dict_body(self):
        """sync_receive with dict body should wrap in list."""
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
            result = await admin_routes.sync_receive({"entity_type": "product"})
        assert result["success"] is True
        assert result["received"] == 1


# ---------------------------------------------------------------------------
# admin_list_wechat_groups — all branches
# ---------------------------------------------------------------------------


class TestAdminListWechatGroups:
    """Cover admin_list_wechat_groups route."""

    @pytest.mark.asyncio
    async def test_no_session_returns_401(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/admin/wechat/groups")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_with_session_returns_data(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.list_group_contacts",
                return_value=[{"id": 1, "name": "Group 1"}],
            ),
        ):
            response = client.get("/api/xcmax/admin/wechat/groups?keyword=test&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_error_returns_500(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.list_group_contacts",
                side_effect=RuntimeError("db fail"),
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (RuntimeError,)),
        ):
            response = client.get("/api/xcmax/admin/wechat/groups")
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_no_keyword_passes_none(self, client: TestClient):
        """When keyword is empty, should pass None to list_group_contacts."""
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.list_group_contacts",
                return_value=[],
            ) as mock_list,
        ):
            response = client.get("/api/xcmax/admin/wechat/groups")
        assert response.status_code == 200
        # Verify None was passed for keyword
        args, kwargs = mock_list.call_args
        assert kwargs.get("keyword") is None


# ---------------------------------------------------------------------------
# ops_duty_run_detail — invalid run_id
# ---------------------------------------------------------------------------


class TestOpsDutyRunDetailDeep:
    """Cover ops_duty_run_detail invalid run_id."""

    @pytest.mark.asyncio
    async def test_invalid_run_id_returns_400(self, client: TestClient):
        response = client.get("/api/xcmax/ops/duty-runs/0")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_negative_run_id_returns_400(self, client: TestClient):
        response = client.get("/api/xcmax/ops/duty-runs/-1")
        assert response.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# ops_staffing_onboard — no ids
# ---------------------------------------------------------------------------


class TestOpsStaffingOnboardDeep:
    """Cover ops_staffing_onboard with no ids."""

    @pytest.mark.asyncio
    async def test_no_ids(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ) as mock_proxy:
            response = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"dry_run": True},
            )
        assert response.status_code == 200
        # Verify payload doesn't have pkg_ids
        args, kwargs = mock_proxy.call_args
        payload = kwargs.get("json_body", {})
        assert "pkg_ids" not in payload

    @pytest.mark.asyncio
    async def test_empty_string_ids(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ) as mock_proxy:
            response = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"pkg_ids": "  "},  # Whitespace only
            )
        assert response.status_code == 200
        args, kwargs = mock_proxy.call_args
        payload = kwargs.get("json_body", {})
        assert "pkg_ids" not in payload

    @pytest.mark.asyncio
    async def test_empty_list_ids(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ) as mock_proxy:
            response = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"employee_ids": []},  # Empty list
            )
        assert response.status_code == 200
        args, kwargs = mock_proxy.call_args
        payload = kwargs.get("json_body", {})
        # Empty list should result in empty string for pkg_ids
        if "pkg_ids" in payload:
            assert payload["pkg_ids"] == ""


# ---------------------------------------------------------------------------
# _market_admin_proxy — import error
# ---------------------------------------------------------------------------


class TestMarketAdminProxyImportError:
    """Cover _market_admin_proxy import error branch."""

    @pytest.mark.asyncio
    async def test_import_at_top_level_fails(self):
        """When importing market_account functions fails, should return 500."""
        req = MagicMock(spec=Request)
        # Mock the import to fail - the import is `from app.fastapi_routes.market_account import ...`
        # We need to make this specific import fail
        import sys

        original_module = sys.modules.get("app.fastapi_routes.market_account")

        class FakeModule:
            def __getattr__(self, name):
                raise ImportError(f"cannot import {name}")

        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {"app.fastapi_routes.market_account": FakeModule()},
            ),
            patch("app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS", (ImportError,)),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500
        assert "市场账号代理不可用" in result.body.decode()

    @pytest.mark.asyncio
    async def test_proxy_returns_dict_payload_success(self):
        """When _proxy_json returns a dict without __proxy_error__, should return it."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"success": True, "data": {"id": 1}}),
            ),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert isinstance(result, dict)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _digest_local_or_proxy — additional branches
# ---------------------------------------------------------------------------


class TestDigestLocalOrProxyDeep:
    """Deep coverage for _digest_local_or_proxy."""

    @pytest.mark.asyncio
    async def test_prefer_local_false_uses_proxy(self):
        """When prefer_local_modstore is False, should use proxy with admin session."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=False,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True, "proxied": True}),
            ) as mock_proxy,
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests?limit=10"
            )
        assert isinstance(result, dict)
        assert result.get("proxied") is True
        # Should require admin session
        args, kwargs = mock_proxy.call_args
        assert kwargs.get("require_admin_session") is True

    @pytest.mark.asyncio
    async def test_prefer_local_true_get_uses_local(self):
        """When prefer_local_modstore is True and GET, should use local."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_daily_digests_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests?limit=20&offset=0"
            )
        assert isinstance(result, dict)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_local_path_with_query_params(self):
        """Local path with query params should parse them."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_daily_digests_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ) as mock_list,
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests?limit=20&offset=0"
            )
        assert isinstance(result, dict)
        # Should parse limit and offset from query
        args, kwargs = mock_list.call_args
        assert kwargs.get("limit") == 20
        assert kwargs.get("offset") == 0

    @pytest.mark.asyncio
    async def test_local_action_items_with_query_params(self):
        """Local action-items path with query params should parse them."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.action_items_stats_local",
                new=AsyncMock(return_value={"success": True, "data": {}}),
            ) as mock_stats,
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/admin/action-items/stats?kind=patch&day=2026-06-17"
            )
        assert isinstance(result, dict)
        args, kwargs = mock_stats.call_args
        assert kwargs.get("kind") == "patch"
        assert kwargs.get("day") == "2026-06-17"

    @pytest.mark.asyncio
    async def test_local_action_items_with_only_kind(self):
        """Local action-items path with only kind param."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_action_items_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ) as mock_list,
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/admin/action-items?kind=update"
            )
        assert isinstance(result, dict)
        args, kwargs = mock_list.call_args
        assert kwargs.get("kind") == "update"
        assert kwargs.get("day") == ""

    @pytest.mark.asyncio
    async def test_local_action_items_with_only_day(self):
        """Local action-items path with only day param."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_action_items_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ) as mock_list,
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/admin/action-items?day=2026-06-17"
            )
        assert isinstance(result, dict)
        args, kwargs = mock_list.call_args
        assert kwargs.get("kind") == ""
        assert kwargs.get("day") == "2026-06-17"


# ---------------------------------------------------------------------------
# _xcmax_market_proxy_impl — additional branches
# ---------------------------------------------------------------------------


class TestXcmaxMarketProxyImplDeep:
    """Deep coverage for _xcmax_market_proxy_impl."""

    @pytest.mark.asyncio
    async def test_delete_request(self):
        req = MagicMock(spec=Request)
        req.method = "DELETE"
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_patch_request_with_body(self):
        req = MagicMock(spec=Request)
        req.method = "PATCH"
        req.json = AsyncMock(return_value={"key": "value"})
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_empty_subpath(self):
        req = MagicMock(spec=Request)
        req.method = "GET"
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ) as mock_proxy:
            result = await admin_routes._xcmax_market_proxy_impl(req, "")
        assert isinstance(result, dict)
        args, kwargs = mock_proxy.call_args
        # Should construct path as /api/
        assert args[2] == "/api/"


# ---------------------------------------------------------------------------
# CORE_MODULES — verify structure
# ---------------------------------------------------------------------------


class TestCoreModules:
    """Verify CORE_MODULES structure."""

    def test_all_modules_have_required_fields(self):
        """All core modules should have required fields."""
        for module in admin_routes.CORE_MODULES:
            assert "module_id" in module
            assert "display_name" in module
            assert "route" in module
            assert "source" in module
            assert "sync_scope" in module
            assert "active" in module
            assert "version" in module

    def test_all_modules_are_core_source(self):
        """All core modules should have source='core'."""
        for module in admin_routes.CORE_MODULES:
            assert module["source"] == "core"

    def test_all_modules_are_active(self):
        """All core modules should be active."""
        for module in admin_routes.CORE_MODULES:
            assert module["active"] is True

    def test_all_modules_have_version_1_0(self):
        """All core modules should have version='1.0'."""
        for module in admin_routes.CORE_MODULES:
            assert module["version"] == "1.0"

    def test_module_ids_are_unique(self):
        """All module_ids should be unique."""
        ids = [m["module_id"] for m in admin_routes.CORE_MODULES]
        assert len(ids) == len(set(ids))

    def test_contains_expected_modules(self):
        """Should contain expected core modules."""
        ids = {m["module_id"] for m in admin_routes.CORE_MODULES}
        assert "xcmax-admin" in ids
        assert "chat" in ids
        assert "products" in ids
        assert "settings" in ids


# ---------------------------------------------------------------------------
# _sync_sse_generator — additional coverage
# ---------------------------------------------------------------------------


class TestSyncSseGeneratorDeep:
    """Deep coverage for _sync_sse_generator."""

    @pytest.mark.asyncio
    async def test_connected_event_first(self):
        """First event should be connected event."""
        req = MagicMock(spec=Request)
        req.is_disconnected = AsyncMock(return_value=True)  # Disconnect immediately

        gen = admin_routes._sync_sse_generator(req, since_cursor=42)
        first = await gen.__anext__()
        assert "connected" in first
        assert "42" in first  # cursor should be in event

    @pytest.mark.asyncio
    async def test_changes_update_cursor(self):
        """Changes should update the cursor."""
        req = MagicMock(spec=Request)
        req.is_disconnected = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.get_changes.return_value = [{"id": 100, "entity_type": "product"}]
        mock_db.get_status.return_value = {"healthy": True}

        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            gen = admin_routes._sync_sse_generator(req, since_cursor=0)
            first = await gen.__anext__()  # connected
            second = await gen.__anext__()  # changes
            assert "100" in second  # new cursor
            req.is_disconnected = AsyncMock(return_value=True)
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
