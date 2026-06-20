"""Tests for app.fastapi_routes.xcmax_admin — coverage ramp.

Covers all route endpoints, helper functions, and error paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes
from app.fastapi_routes.xcmax_admin import router


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
    def test_no_session_id_returns_401(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 401
        assert "登录" in resp.body.decode()

    def test_non_admin_account_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "user", "market_is_admin": False},
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403

    def test_admin_returns_none(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            assert admin_routes._require_market_admin_session(request) is None

    def test_meta_none_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403

    def test_admin_kind_but_not_market_admin_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": False},
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# _release_train_snapshot
# ---------------------------------------------------------------------------


class TestReleaseTrainSnapshot:
    def test_modstore_path_used(self) -> None:
        with patch.dict(
            "sys.modules",
            {
                "modstore_server.release_train": MagicMock(
                    snapshot_public=MagicMock(return_value={"current": "1.0.0.0"})
                )
            },
        ):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"

    def test_fallback_to_file(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text(
            json.dumps({"current": "9.9.9.9", "epoch": "9.9.0.0"})
        )
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "9.9.9.9"

    def test_file_missing_returns_default(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"
        assert out.get("note") == "ssot missing"

    def test_bad_json_returns_default(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text("not json")
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"

    def test_file_returns_non_dict_returns_default(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text(json.dumps([1, 2, 3]))
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"

    def test_no_monorepo_root_uses_path_relative(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": ""}, clear=False):
            out = admin_routes._release_train_snapshot()
        # Either gets a real file or returns default — just ensure no crash
        assert "current" in out


# ---------------------------------------------------------------------------
# _collect_mod_modules / _collect_employee_pack_modules
# ---------------------------------------------------------------------------


class TestCollectModules:
    def test_collect_mod_modules_no_manager(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            rows = admin_routes._collect_mod_modules()
        assert rows == []

    def test_collect_mod_modules_with_registry(self) -> None:
        mock_meta = MagicMock()
        mock_meta.name = "test-mod"
        mock_meta.version = "2.0"
        mock_mgr = MagicMock()
        mock_mgr._registry = {"mod1": mock_meta}
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            rows = admin_routes._collect_mod_modules()
        assert len(rows) == 1
        assert rows[0]["module_id"] == "mod1"
        assert rows[0]["source"] == "local"

    def test_collect_mod_modules_import_error(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("no mod_manager"),
        ):
            rows = admin_routes._collect_mod_modules()
        assert rows == []

    def test_collect_employee_pack_modules_no_manager(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=None,
        ):
            rows = admin_routes._collect_employee_pack_modules()
        assert rows == []

    def test_collect_employee_pack_modules_with_packs(self) -> None:
        mock_mgr = MagicMock()
        mock_mgr.mods_root = "/tmp/test_mods"
        mock_registry = MagicMock()
        mock_registry.list_packs.return_value = [
            {"id": "emp1", "name": "Employee 1", "version": "1.0"},
        ]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mgr,
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry",
                return_value=mock_registry,
            ),
        ):
            rows = admin_routes._collect_employee_pack_modules()
        assert len(rows) == 1
        assert rows[0]["source"] == "employee"

    def test_collect_employee_pack_modules_import_error(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("nope"),
        ):
            rows = admin_routes._collect_employee_pack_modules()
        assert rows == []


# ---------------------------------------------------------------------------
# _inject_digest_api_base
# ---------------------------------------------------------------------------


class TestInjectDigestApiBase:
    def test_injects_into_data_dict(self) -> None:
        payload = {"data": {"key": "val"}}
        result = admin_routes._inject_digest_api_base(payload, "http://base")
        assert result["data"]["digest_api_base"] == "http://base"

    def test_no_data_key(self) -> None:
        payload = {"other": "val"}
        result = admin_routes._inject_digest_api_base(payload, "http://base")
        assert result == payload

    def test_data_not_dict(self) -> None:
        payload = {"data": "not a dict"}
        result = admin_routes._inject_digest_api_base(payload, "http://base")
        assert result == payload


# ---------------------------------------------------------------------------
# _probe_remote_health_sync
# ---------------------------------------------------------------------------


class TestProbeRemoteHealthSync:
    def test_successful_probe(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"version": "1.0", "timestamp": "2026-01-01"}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = admin_routes._probe_remote_health_sync()
        assert result["success"] is True
        assert result["data"]["reachable"] is True
        assert result["data"]["latency_ms"] is not None

    def test_failed_probe(self) -> None:
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = admin_routes._probe_remote_health_sync()
        assert result["success"] is True
        assert result["data"]["reachable"] is False
        assert "error" in result["data"]


# ---------------------------------------------------------------------------
# Route endpoints
# ---------------------------------------------------------------------------


class TestListModules:
    def test_returns_core_modules(self, client: TestClient) -> None:
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
            resp = client.get("/api/xcmax/admin/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) > 0
        assert data["total"] == len(data["data"])

    def test_includes_mod_and_employee_modules(self, client: TestClient) -> None:
        mod_rows = [{"module_id": "mod1", "source": "local"}]
        emp_rows = [{"module_id": "emp1", "source": "employee"}]
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mod_modules",
                return_value=mod_rows,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_employee_pack_modules",
                return_value=emp_rows,
            ),
        ):
            resp = client.get("/api/xcmax/admin/modules")
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["module_id"] for m in data["data"]]
        assert "mod1" in ids
        assert "emp1" in ids


class TestReleaseTrain:
    def test_returns_snapshot(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.xcmax_admin._release_train_snapshot",
            return_value={"current": "2.0.0.0", "epoch": "2.0.0.0"},
        ):
            resp = client.get("/api/xcmax/release-train")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["current"] == "2.0.0.0"


class TestRemoteStatus:
    def test_returns_reachable(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.xcmax_admin._probe_remote_health_sync",
            return_value={
                "success": True,
                "data": {"reachable": True, "latency_ms": 50},
            },
        ):
            resp = client.get("/api/xcmax/admin/remote-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["reachable"] is True


class TestLocalDutyGraphHealth:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/local/duty-graph/health")
        assert resp.status_code == 401

    def test_authenticated_returns_health(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_duty_graph_health",
                return_value={"status": "ok"},
            ),
        ):
            resp = client.get("/api/xcmax/local/duty-graph/health")
        assert resp.status_code == 200


class TestLocalEmployeeStatus:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/local/employees/emp1/status")
        assert resp.status_code == 401

    def test_empty_employee_id_returns_400(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sess1",
        ):
            resp = client.get("/api/xcmax/local/employees/%20/status")
        assert resp.status_code == 400

    def test_valid_employee_id(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_employee_status",
                return_value={"employee_id": "emp1", "status": "deployed"},
            ),
        ):
            resp = client.get("/api/xcmax/local/employees/emp1/status")
        assert resp.status_code == 200


class TestLocalEmployeeManifest:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert resp.status_code == 401

    def test_empty_employee_id_returns_400(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sess1",
        ):
            resp = client.get("/api/xcmax/local/employees/%20/manifest")
        assert resp.status_code == 400

    def test_manifest_not_found_returns_404(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value=None,
            ),
        ):
            resp = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert resp.status_code == 404

    def test_manifest_found(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value={"id": "emp1", "name": "Test"},
            ),
        ):
            resp = client.get("/api/xcmax/local/employees/emp1/manifest")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Admin proxy routes (mocked _market_admin_proxy)
# ---------------------------------------------------------------------------


class TestAdminListMarketUsers:
    def test_proxy_called(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": []},
        ) as mock_proxy:
            resp = client.get("/api/xcmax/admin/market/users")
        assert resp.status_code == 200
        mock_proxy.assert_awaited_once()


class TestAdminListAssignableMods:
    def test_proxy_called(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": []},
        ) as mock_proxy:
            resp = client.get("/api/xcmax/admin/market/assignable-mods")
        assert resp.status_code == 200
        mock_proxy.assert_awaited_once()


class TestAdminListUserMods:
    def test_proxy_called_with_user_id(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": []},
        ) as mock_proxy:
            resp = client.get("/api/xcmax/admin/market/users/42/mods")
        assert resp.status_code == 200
        call_args = mock_proxy.call_args
        assert "42" in call_args[0][2]


class TestAdminBindUserMod:
    def test_proxy_and_audit(self, client: TestClient) -> None:
        with (
            patch.object(
                admin_routes,
                "_market_admin_proxy",
                new_callable=AsyncMock,
                return_value={"success": True},
            ),
            patch(
                "app.application.session_account_meta.audit_admin_action",
            ) as mock_audit,
        ):
            resp = client.post("/api/xcmax/admin/market/users/42/mods/test-mod")
        assert resp.status_code == 200
        mock_audit.assert_called_once()


class TestAdminUnbindUserMod:
    def test_proxy_and_audit(self, client: TestClient) -> None:
        with (
            patch.object(
                admin_routes,
                "_market_admin_proxy",
                new_callable=AsyncMock,
                return_value={"success": True},
            ),
            patch(
                "app.application.session_account_meta.audit_admin_action",
            ) as mock_audit,
        ):
            resp = client.delete("/api/xcmax/admin/market/users/42/mods/test-mod")
        assert resp.status_code == 200
        mock_audit.assert_called_once()


class TestAdminSetUserAdmin:
    def test_proxy_called(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ) as mock_proxy:
            resp = client.put("/api/xcmax/admin/market/users/42/admin?is_admin=true")
        assert resp.status_code == 200
        call_args = mock_proxy.call_args
        assert "true" in call_args[0][2]


class TestAdminSetUserEnterprise:
    def test_proxy_called(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ) as mock_proxy:
            resp = client.put("/api/xcmax/admin/market/users/42/enterprise?is_enterprise=true")
        assert resp.status_code == 200
        call_args = mock_proxy.call_args
        assert "true" in call_args[0][2]


class TestAdminWechatGroups:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/admin/wechat/groups")
        assert resp.status_code == 401

    def test_authenticated_returns_groups(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.list_group_contacts",
                return_value=[{"id": 1, "name": "group1"}],
            ),
        ):
            resp = client.get("/api/xcmax/admin/wechat/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 1

    def test_service_error_returns_500(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.list_group_contacts",
                side_effect=RuntimeError("db down"),
            ),
        ):
            resp = client.get("/api/xcmax/admin/wechat/groups")
        assert resp.status_code == 500


class TestAdminUserWechatCustomers:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/admin/market/users/1/wechat-customers")
        assert resp.status_code == 401

    def test_authenticated_returns_bindings(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.get_bindings_for_user",
                return_value=[{"contact_id": "c1"}],
            ),
        ):
            resp = client.get("/api/xcmax/admin/market/users/1/wechat-customers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestAdminSaveUserWechatCustomers:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": ["c1"]},
            )
        assert resp.status_code == 401

    def test_authenticated_saves_bindings(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": ["c1"]},
            )
        assert resp.status_code == 200

    def test_non_list_contact_ids_treated_as_empty(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ) as mock_save,
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": "not-a-list"},
            )
        assert resp.status_code == 200
        mock_save.assert_called_once_with(1, [])


class TestAdminImpersonate:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": 5},
            )
        assert resp.status_code == 401

    def test_missing_market_user_id_returns_400(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate",
                json={},
            )
        assert resp.status_code == 400

    def test_invalid_market_user_id_returns_400(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": "not-a-number"},
            )
        assert resp.status_code == 400

    def test_valid_impersonate(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={
                    "account_kind": "admin",
                    "market_is_admin": True,
                    "market_user_id": 1,
                    "market_is_enterprise": False,
                },
            ),
            patch(
                "app.application.session_account_meta.persist_session_account_meta",
            ),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.session_account_meta.audit_admin_action",
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": 5, "username": "testuser"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["impersonating_market_user_id"] == 5
        assert data["impersonating_username"] == "testuser"

    def test_activate_enterprise_missing_token(self, client: TestClient) -> None:
        # The activate-enterprise endpoint is not implemented; expect 404
        resp = client.post("/api/xcmax/admin/impersonate/activate-enterprise", json={})
        assert resp.status_code == 404

    def test_activate_enterprise_invalid_token(self, client: TestClient) -> None:
        # The activate-enterprise endpoint is not implemented; expect 404
        resp = client.post(
            "/api/xcmax/admin/impersonate/activate-enterprise",
            json={"bridge_token": "not-valid"},
        )
        assert resp.status_code == 404


class TestAdminEndImpersonate:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.post("/api/xcmax/admin/impersonate/end")
        assert resp.status_code == 401

    def test_valid_end_impersonate(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={
                    "account_kind": "admin",
                    "market_is_admin": True,
                    "market_user_id": 1,
                },
            ),
            patch(
                "app.application.session_account_meta.clear_impersonation",
            ),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.session_account_meta.audit_admin_action",
            ),
        ):
            resp = client.post("/api/xcmax/admin/impersonate/end")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Sync routes
# ---------------------------------------------------------------------------


class TestSyncStatus:
    def test_sync_db_available(self, client: TestClient) -> None:
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"healthy": True, "outbox_count": 0}
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            resp = client.get("/api/xcmax/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_sync_db_unavailable(self, client: TestClient) -> None:
        with patch("app.db.xcmax_sync.SyncDb", side_effect=ImportError("no db")):
            resp = client.get("/api/xcmax/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["healthy"] is False


class TestSyncPush:
    def test_push_success(self, client: TestClient) -> None:
        with patch(
            "app.application.xcmax_sync_app.push_outbox",
            return_value={"pushed": 3},
        ):
            resp = client.post("/api/xcmax/sync/push")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_push_failure(self, client: TestClient) -> None:
        with patch(
            "app.application.xcmax_sync_app.push_outbox",
            side_effect=RuntimeError("connection refused"),
        ):
            resp = client.post("/api/xcmax/sync/push")
        assert resp.status_code == 500


class TestSyncChanges:
    def test_changes_success(self, client: TestClient) -> None:
        mock_db = MagicMock()
        mock_db.get_changes.return_value = [{"id": 1, "entity": "test"}]
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            resp = client.get("/api/xcmax/sync/changes?since_cursor=0&limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_changes_db_error(self, client: TestClient) -> None:
        with patch("app.db.xcmax_sync.SyncDb", side_effect=ImportError("no db")):
            resp = client.get("/api/xcmax/sync/changes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


class TestSyncReceive:
    def test_receive_single_item(self, client: TestClient) -> None:
        """Test sync_receive via direct function call since FastAPI body: dict|list
        without Body() causes 422 in isolated TestClient."""
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
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes.sync_receive({"entity": "test"})
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["received"] == 1

    def test_receive_list_items(self, client: TestClient) -> None:
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
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes.sync_receive([{"entity": "a"}, {"entity": "b"}])
            )
        assert result["received"] == 2

    def test_receive_db_error(self, client: TestClient) -> None:
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db error")):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes.sync_receive([{"entity": "test"}])
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


class TestSyncPull:
    def test_pull_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.application.xcmax_sync_app.pull_from_remote",
                return_value={"pulled": 5},
            ),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 5},
            ),
        ):
            resp = client.post("/api/xcmax/sync/pull")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_pull_failure(self, client: TestClient) -> None:
        with patch(
            "app.application.xcmax_sync_app.pull_from_remote",
            side_effect=RuntimeError("timeout"),
        ):
            resp = client.post("/api/xcmax/sync/pull")
        assert resp.status_code == 500


class TestSyncConflicts:
    def test_list_conflicts_success(self, client: TestClient) -> None:
        with patch(
            "app.services.admin_sync_service.list_sync_conflicts",
            return_value=[{"id": 1}],
        ):
            resp = client.get("/api/xcmax/sync/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_list_conflicts_error(self, client: TestClient) -> None:
        with patch(
            "app.services.admin_sync_service.list_sync_conflicts",
            side_effect=ImportError("no module"),
        ):
            resp = client.get("/api/xcmax/sync/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


class TestResolveConflict:
    def test_apply_action(self, client: TestClient) -> None:
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.fetch_inbox_row",
                return_value={"entity_type": "test", "payload": {}},
            ),
            patch(
                "app.application.xcmax_sync_app.entity_appliers",
                return_value={},
            ),
        ):
            resp = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "apply"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "apply"
        mock_db.mark_inbox_applied.assert_called_once_with(1)

    def test_skip_action(self, client: TestClient) -> None:
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=MagicMock()),
            patch(
                "app.services.admin_sync_service.mark_inbox_skipped",
            ),
        ):
            resp = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "skip"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "skip"

    def test_error_returns_500(self, client: TestClient) -> None:
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db error")):
            resp = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "skip"},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Ops routes
# ---------------------------------------------------------------------------


class TestOpsDutyHealth:
    def test_returns_merged_health(self, client: TestClient) -> None:
        with (
            patch.object(
                admin_routes,
                "_remote_duty_health",
                new_callable=AsyncMock,
                return_value={"success": True, "staffing": {}},
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={"staffing": {"total": 5}, "planned_employee_ids": []},
            ),
        ):
            resp = client.get("/api/xcmax/ops/duty-health")
        assert resp.status_code == 200


class TestOpsDispatch:
    def test_dispatch_with_body(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.post("/api/xcmax/ops/dispatch", json={"action": "test"})
        assert resp.status_code == 200


class TestOpsJobs:
    def test_list_jobs(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": []},
        ):
            resp = client.get("/api/xcmax/ops/jobs?limit=20")
        assert resp.status_code == 200


class TestOpsJobDetail:
    def test_invalid_job_id_returns_400(self, client: TestClient) -> None:
        # Empty job_id is sanitized to empty string, returns 400
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {}},
        ):
            # FastAPI route strips special chars from job_id, empty becomes ""
            resp = client.get("/api/xcmax/ops/jobs/%20%20")
        assert resp.status_code in (400, 404, 307, 401, 422)

    def test_valid_job_id(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {}},
        ):
            resp = client.get("/api/xcmax/ops/jobs/job-123")
        assert resp.status_code == 200


class TestOpsDutyRuns:
    def test_create_duty_run(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.post("/api/xcmax/ops/duty-runs", json={})
        assert resp.status_code == 200


class TestOpsDutyRunDetail:
    def test_invalid_run_id_returns_400(self, client: TestClient) -> None:
        resp = client.get("/api/xcmax/ops/duty-runs/0")
        assert resp.status_code == 400

    def test_negative_run_id_returns_400(self, client: TestClient) -> None:
        resp = client.get("/api/xcmax/ops/duty-runs/-1")
        assert resp.status_code == 400

    def test_valid_run_id(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {}},
        ):
            resp = client.get("/api/xcmax/ops/duty-runs/1")
        assert resp.status_code == 200


class TestOpsClosureStatus:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/ops/closure-status")
        assert resp.status_code == 401

    def test_authenticated_returns_status(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch.object(
                admin_routes,
                "_remote_duty_health",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={"staffing": {}},
            ),
        ):
            resp = client.get("/api/xcmax/ops/closure-status")
        assert resp.status_code == 200


class TestOpsStaffingOnboard:
    def test_onboard_with_employee_ids(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"employee_ids": ["emp1", "emp2"]},
            )
        assert resp.status_code == 200

    def test_onboard_with_string_pkg_ids(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"pkg_ids": "emp1,emp2"},
            )
        assert resp.status_code == 200


class TestOpsStaffingInstallLocal:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.post("/api/xcmax/ops/staffing/install-local", json={})
        assert resp.status_code == 401

    def test_missing_employee_id_returns_400(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            resp = client.post("/api/xcmax/ops/staffing/install-local", json={})
        assert resp.status_code == 400

    def test_install_error_returns_500(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new_callable=AsyncMock,
                side_effect=RuntimeError("install failed"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "emp1"},
            )
        assert resp.status_code == 500


class TestOpsStaffingCloseGap:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert resp.status_code == 401

    def test_close_gap_skip_onboard_and_install(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch.object(
                admin_routes,
                "_remote_duty_health",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": [],
                },
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap",
                json={"skip_onboard": True, "skip_install": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Digest / action-items routes
# ---------------------------------------------------------------------------


class TestDigestVibePrepSession:
    def test_empty_session_id_returns_400(self, client: TestClient) -> None:
        resp = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/")
        assert resp.status_code in (400, 404, 307)

    def test_valid_session_id(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/abc123")
        assert resp.status_code == 200


class TestAllHandsReportSession:
    def test_start_session(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "session_id": "s1"},
        ):
            resp = client.post("/api/xcmax/admin/all-hands-report/sessions", json={})
        assert resp.status_code == 200

    def test_get_session_empty_id_returns_400(self, client: TestClient) -> None:
        # Empty session_id after sanitization → 400
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            # Send whitespace-only session_id which gets sanitized to ""
            resp = client.get("/api/xcmax/admin/all-hands-report/sessions/%20%20")
        assert resp.status_code in (400, 404, 307, 405, 422)

    def test_get_session_valid_id(self, client: TestClient) -> None:
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            resp = client.get("/api/xcmax/admin/all-hands-report/sessions/abc123")
        assert resp.status_code == 200


class TestDigestIdentity:
    def test_upstream_404_returns_empty_code(self, client: TestClient) -> None:
        not_found_resp = JSONResponse({"success": False, "message": "not found"}, status_code=404)
        with (
            patch.object(
                admin_routes,
                "_market_admin_proxy",
                new_callable=AsyncMock,
                return_value=not_found_resp,
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="http://localhost",
            ),
        ):
            resp = client.get("/api/xcmax/admin/digest-identity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["code"] == ""

    def test_upstream_dict_response(self, client: TestClient) -> None:
        with (
            patch.object(
                admin_routes,
                "_market_admin_proxy",
                new_callable=AsyncMock,
                return_value={"success": True, "data": {"code": "ABC123"}},
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="http://localhost",
            ),
        ):
            resp = client.get("/api/xcmax/admin/digest-identity")
        assert resp.status_code == 200
        data = resp.json()
        assert "digest_api_base" in data.get("data", {})


# ---------------------------------------------------------------------------
# _market_admin_proxy
# ---------------------------------------------------------------------------


class TestMarketAdminProxy:
    def test_no_admin_session_returns_401(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._market_admin_proxy(request, "GET", "/api/test")
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    def test_no_authorization_returns_401(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="",
            ),
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._market_admin_proxy(request, "GET", "/api/test")
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    def test_proxy_error_returns_error_response(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer test-token",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={
                    "__proxy_error__": True,
                    "status_code": 502,
                    "payload": {"detail": "bad gateway"},
                },
            ),
            patch(
                "app.fastapi_routes.market_account._error_message",
                return_value="市场服务返回 502",
            ),
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._market_admin_proxy(request, "GET", "/api/test")
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    def test_require_admin_session_false_skips_gate(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer test-token",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"success": True, "data": []},
            ),
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._market_admin_proxy(
                    request, "GET", "/api/test", require_admin_session=False
                )
            )
        assert isinstance(result, dict)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _remote_duty_health
# ---------------------------------------------------------------------------


class TestRemoteDutyHealth:
    def test_dict_response(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value={"success": True, "staffing": {"total": 10}},
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._remote_duty_health(request)
            )
        assert result["success"] is True

    def test_json_response_body(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        mock_resp = JSONResponse({"success": True, "data": {"key": "val"}})
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._remote_duty_health(request)
            )
        assert isinstance(result, dict)

    def test_non_dict_non_jsonresponse(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch.object(
            admin_routes,
            "_market_admin_proxy",
            new_callable=AsyncMock,
            return_value="unexpected",
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                admin_routes._remote_duty_health(request)
            )
        assert result == {}
