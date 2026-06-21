"""Coverage ramp for app/fastapi_routes/system_routes.py."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes import system_routes as mod
from app.fastapi_routes.system_routes import (
    IndustriesListData,
    IndustryData,
    IndustryResponse,
    SetIndustryRequest,
    _build_industry_response,
    get_current_industry_endpoint,
    get_employee_registry_rules,
    get_host_profile,
    get_industries,
    get_industry_detail,
    get_industry_presets,
    get_workflow_employee_catalog,
    router,
    set_industry_endpoint,
)
from app.infrastructure.auth.dependencies import require_admin_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    name: str = "涂料",
    units: dict | None = None,
    quantity_fields: dict | None = None,
    product_fields: dict | None = None,
    order_types: dict | None = None,
    print_config: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        units=units or {"桶": {"abbr": "t"}},
        quantity_fields=quantity_fields or {"primary_field": "tins"},
        product_fields=product_fields or {"name": "name"},
        order_types=order_types or {"shipment": "发货单"},
        print_config=print_config or {"template": "default"},
    )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    # POST /api/system/industry 现在受 require_admin_user 门禁保护（仅管理端账号可
    # 切换行业）。这里注入一个管理端用户，使测试得以验证端点内部的业务逻辑分支
    # （行业切换 / 工作区偏好保存 / 企业授权过滤 / mod 去激活），而非每个用例都被
    # 401/403 拦在门外。需要验证「企业账号未开通行业」的用例仍会触发端点内部 403。
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=1, username="admin", tier="admin"
    )
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestIndustryResponseModel:
    def test_defaults(self) -> None:
        m = IndustryResponse(id="x", name="X", code="x")
        assert m.description == ""
        assert m.config == {}

    def test_with_config(self) -> None:
        m = IndustryResponse(id="x", name="X", code="x", config={"k": "v"})
        assert m.config == {"k": "v"}


class TestIndustriesListDataModel:
    def test_basic(self) -> None:
        m = IndustriesListData(industries=[{"id": "a"}], current="a")
        assert m.industries == [{"id": "a"}]
        assert m.current == "a"


class TestIndustryDataModel:
    def test_basic(self) -> None:
        m = IndustryData(industry={"id": "a"})
        assert m.industry == {"id": "a"}


class TestSetIndustryRequestModel:
    def test_basic(self) -> None:
        m = SetIndustryRequest(industry_id="涂料")
        assert m.industry_id == "涂料"

    def test_missing_field_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SetIndustryRequest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# _build_industry_response
# ---------------------------------------------------------------------------


class TestBuildIndustryResponse:
    def test_basic(self) -> None:
        profile = _make_profile()
        out = _build_industry_response("涂料", profile)
        assert out["id"] == "涂料"
        assert out["name"] == "涂料"
        assert out["code"] == "涂料"
        assert out["description"] == "涂料"
        assert out["config"]["units"] == profile.units
        assert out["config"]["quantity_fields"] == profile.quantity_fields
        assert out["config"]["product_fields"] == profile.product_fields
        assert out["config"]["order_types"] == profile.order_types
        assert out["config"]["print_config"] == profile.print_config


# ---------------------------------------------------------------------------
# get_industries
# ---------------------------------------------------------------------------


class TestGetIndustries:
    def test_success(self, client: TestClient) -> None:
        # Build a fake industry_config module
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
            {"id": "食品", "name": "食品"},
        ]
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industries")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["current"] == "涂料"
        assert len(body["data"]["industries"]) == 2
        assert body["data"]["industries"][0]["id"] == "涂料"

    def test_enterprise_filter_limits_industries(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "考勤", "name": "考勤"},
            {"id": "涂料", "name": "涂料"},
        ]
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.fastapi_routes.system_routes._allowed_industry_ids_for_request",
                new=AsyncMock(return_value=({"考勤"}, "考勤")),
            ),
        ):
            r = client.get("/api/system/industries")
        assert r.status_code == 200
        body = r.json()
        assert [x["id"] for x in body["data"]["industries"]] == ["考勤"]
        assert body["data"]["current"] == "考勤"

    def test_error_500(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.side_effect = ValueError("boom")
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industries")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_current_industry_endpoint
# ---------------------------------------------------------------------------


class TestGetCurrentIndustryEndpoint:
    def test_success_no_user(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        # resolve_session_user returns None (no user)
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["id"] == "涂料"

    def test_success_with_user_and_saved_pref(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        user = SimpleNamespace(id=1, username="u")
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
                return_value=1,
            ),
            patch(
                "app.application.tenant_workspace_prefs.get_selected_industry_id",
                return_value="食品",
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        # current_id should be overridden by saved pref "食品"
        body = r.json()
        assert body["data"]["id"] == "食品"

    def test_enterprise_filter_overrides_saved_unauthorized_industry(
        self, client: TestClient
    ) -> None:
        fake_module = MagicMock()
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        user = SimpleNamespace(id=1, username="SUNBIRD")
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
                return_value=1,
            ),
            patch(
                "app.application.tenant_workspace_prefs.get_selected_industry_id",
                return_value="涂料",
            ),
            patch(
                "app.fastapi_routes.system_routes._allowed_industry_ids_for_request",
                new=AsyncMock(return_value=({"考勤"}, "考勤")),
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "考勤"

    def test_workspace_prefs_lookup_skipped_on_error(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_current_industry.return_value = "涂料"
        fake_module.get_industry_profile.return_value = _make_profile()
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                side_effect=ValueError("no session"),
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "涂料"

    def test_fallback_to_default_on_error(self, client: TestClient) -> None:
        # First call to get_current_industry raises, fallback path uses "涂料"
        fake_module = MagicMock()
        fake_module.get_current_industry.side_effect = ValueError("boom")
        fake_module.get_industry_profile.return_value = _make_profile()
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["id"] == "涂料"

    def test_fallback_also_fails_returns_500(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_current_industry.side_effect = ValueError("boom")
        fake_module.get_industry_profile.side_effect = ValueError("boom2")
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# set_industry_endpoint
# ---------------------------------------------------------------------------


class TestSetIndustryEndpoint:
    def test_success_no_user(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.return_value = True
        fake_module.get_industry_profile.return_value = _make_profile()
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
        ):
            r = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["id"] == "涂料"

    def test_unknown_industry_400(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.return_value = False
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.post("/api/system/industry", json={"industry_id": "unknown"})
        assert r.status_code == 400
        assert "Unknown industry" in r.json()["detail"]

    def test_success_with_user_and_mod_id(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.return_value = True
        fake_module.get_industry_profile.return_value = _make_profile()
        user = SimpleNamespace(id=1, username="u")
        cat = {
            "enterprise_filter_applied": False,
            "open_packages": [{"industry_id": "涂料", "mod_id": "mod-1"}],
            "open_industry_ids": ["涂料"],
        }
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
                return_value=1,
            ),
            patch(
                "app.application.tenant_workspace_prefs.save_selected_industry",
            ) as mock_save,
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=cat),
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
                return_value="mod-1",
            ),
            patch(
                "app.mod_sdk.industry_seed.industry_mod_id_for",
                return_value="mod-1",
            ),
            patch(
                "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
            ) as mock_deactivate,
        ):
            r = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert r.status_code == 200
        mock_save.assert_called_once()
        mock_deactivate.assert_called_once_with("mod-1")

    def test_enterprise_filter_blocks_industry(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.return_value = True
        user = SimpleNamespace(id=1, username="u")
        cat = {
            "enterprise_filter_applied": True,
            "open_packages": [],
            "open_industry_ids": ["other"],
        }
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
                return_value=1,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=cat),
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
                return_value="mod-1",
            ),
        ):
            r = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert r.status_code == 403
        assert "未开通" in r.json()["detail"]

    def test_workspace_save_error_swallowed(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.return_value = True
        fake_module.get_industry_profile.return_value = _make_profile()
        user = SimpleNamespace(id=1, username="u")
        with (
            patch.dict(sys.modules, {"resources.config.industry_config": fake_module}),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                side_effect=ValueError("no session"),
            ),
        ):
            r = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert r.status_code == 200

    def test_internal_error_500(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.set_current_industry.side_effect = ValueError("boom")
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_host_profile
# ---------------------------------------------------------------------------


class TestGetHostProfile:
    def test_success(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.build_host_profile_api_payload",
            return_value={"sku": "fhd"},
        ):
            r = client.get("/api/system/host-profile")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["sku"] == "fhd"

    def test_error_500(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.build_host_profile_api_payload",
            side_effect=ValueError("boom"),
        ):
            r = client.get("/api/system/host-profile")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_industry_presets
# ---------------------------------------------------------------------------


class TestGetIndustryPresets:
    def test_success_with_preset_ids(self, client: TestClient) -> None:
        doc = {
            "schema_version": 2,
            "preset_ids": ["a", "b"],
            "presets": {"a": {}, "b": {}},
        }
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            return_value=doc,
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["schema_version"] == 2
        assert body["data"]["preset_ids"] == ["a", "b"]
        assert body["data"]["presets"] == {"a": {}, "b": {}}

    def test_success_falls_back_to_presets_keys(self, client: TestClient) -> None:
        doc = {"presets": {"x": {}, "y": {}}}
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            return_value=doc,
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 200
        body = r.json()
        # No preset_ids -> falls back to keys of presets
        assert body["data"]["preset_ids"] == ["x", "y"]
        assert body["data"]["schema_version"] == 1  # default

    def test_error_500(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            side_effect=ValueError("boom"),
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_workflow_employee_catalog
# ---------------------------------------------------------------------------


class TestGetWorkflowEmployeeCatalog:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.host_profile.scan_workflow_employee_catalog_from_mods",
                return_value={"items": []},
            ),
            patch(
                "app.mod_sdk.host_profile.load_host_profile",
                return_value={"workflow_delivery": "monolith", "workflow_monolith_mod_id": "m1"},
            ),
            patch(
                "app.mod_sdk.host_profile.load_workflow_employee_catalog",
                return_value={"static": True},
            ),
        ):
            r = client.get("/api/system/workflow-employee-catalog")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["catalog"] == {"items": []}
        assert body["data"]["workflow_delivery"] == "monolith"
        assert body["data"]["workflow_monolith_mod_id"] == "m1"
        assert body["data"]["static_catalog"] == {"static": True}

    def test_error_500(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.scan_workflow_employee_catalog_from_mods",
            side_effect=ValueError("boom"),
        ):
            r = client.get("/api/system/workflow-employee-catalog")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_employee_registry_rules
# ---------------------------------------------------------------------------


class TestGetEmployeeRegistryRules:
    def test_success(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.get_employee_registry_rules",
            return_value={"rules": []},
        ):
            r = client.get("/api/system/employee-registry-rules")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"] == {"rules": []}

    def test_error_500(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.get_employee_registry_rules",
            side_effect=ValueError("boom"),
        ):
            r = client.get("/api/system/employee-registry-rules")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# get_industry_detail
# ---------------------------------------------------------------------------


class TestGetIndustryDetail:
    def test_success(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
        ]
        fake_module.get_industry_profile.return_value = _make_profile()
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry/涂料")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["id"] == "涂料"

    def test_not_found_404(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
        ]
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry/unknown")
        assert r.status_code == 404
        assert "Industry not found" in r.json()["detail"]

    def test_internal_error_500(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.side_effect = ValueError("boom")
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry/涂料")
        assert r.status_code == 500

    def test_http_exception_propagates(self, client: TestClient) -> None:
        # Even when get_industry_profile raises HTTPException, it should propagate
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
        ]
        fake_module.get_industry_profile.side_effect = HTTPException(
            status_code=418, detail="teapot"
        )
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry/涂料")
        assert r.status_code == 418
