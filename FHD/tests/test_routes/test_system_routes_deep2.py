"""Deep coverage tests for app.fastapi_routes.system_routes.

Targets remaining uncovered branches:
- get_current_industry_endpoint: user is None after resolve_session_user returns None
- get_current_industry_endpoint: user present but owner_id is None
- get_current_industry_endpoint: user present, owner_id present, but saved is None/empty
- get_industries: empty industries list
- get_industry_detail: industry_id with special characters

Retired POST behavior is covered by test_system_routes_ext2 and the real-session,
zero-mutation checks in test_system_routes_industry_admin.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes import system_routes as mod
from app.fastapi_routes.system_routes import (
    IndustriesListData,
    IndustryData,
    IndustryResponse,
    _build_industry_response,
    get_current_industry_endpoint,
    get_employee_registry_rules,
    get_host_profile,
    get_industries,
    get_industry_detail,
    get_industry_presets,
    get_workflow_employee_catalog,
    router,
)


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
    return TestClient(app, raise_server_exceptions=False)


# ── get_current_industry_endpoint deep ──────────────────────────────────────


class TestGetCurrentIndustryEndpointDeep:
    def test_user_present_owner_id_none(self, client: TestClient) -> None:
        """User is present but owner_id resolves to None → no pref lookup."""
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
                return_value=None,
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        # current_id stays as "涂料" (no saved pref)
        assert r.json()["data"]["id"] == "涂料"

    def test_user_present_saved_pref_empty(self, client: TestClient) -> None:
        """User present, owner_id present, but saved pref is empty string."""
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
                return_value="",
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        # Empty saved → current_id stays as "涂料"
        assert r.json()["data"]["id"] == "涂料"

    def test_user_present_saved_pref_none(self, client: TestClient) -> None:
        """User present, owner_id present, but saved pref is None."""
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
                return_value=None,
            ),
        ):
            r = client.get("/api/system/industry")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "涂料"


# ── get_industries deep ─────────────────────────────────────────────────────


class TestGetIndustriesDeep:
    def test_empty_industries_list(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = []
        fake_module.get_current_industry.return_value = "涂料"
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industries")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["industries"] == []
        assert body["data"]["current"] == "涂料"

    def test_multiple_industries(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
            {"id": "食品", "name": "食品"},
            {"id": "电子", "name": "电子"},
        ]
        fake_module.get_current_industry.return_value = "食品"
        fake_module.get_industry_profile.return_value = _make_profile()
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industries")
        assert r.status_code == 200
        body = r.json()
        assert len(body["data"]["industries"]) == 3
        assert body["data"]["current"] == "食品"


# ── get_industry_detail deep ────────────────────────────────────────────────


class TestGetIndustryDetailDeep:
    def test_industry_with_special_characters(self, client: TestClient) -> None:
        fake_module = MagicMock()
        fake_module.get_available_industries.return_value = [
            {"id": "涂料化工", "name": "涂料化工"},
        ]
        fake_module.get_industry_profile.return_value = _make_profile(name="涂料化工")
        with patch.dict(sys.modules, {"resources.config.industry_config": fake_module}):
            r = client.get("/api/system/industry/涂料化工")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "涂料化工"

    def test_http_exception_propagates(self, client: TestClient) -> None:
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


# ── get_host_profile deep ───────────────────────────────────────────────────


class TestGetHostProfileDeep:
    def test_with_complex_payload(self, client: TestClient) -> None:
        payload = {
            "schema_version": 1,
            "profile": {"sku": "enterprise", "editions": {"full": {}}},
            "validation_errors": [],
            "industry_presets_meta": {"schema_version": 1, "preset_count": 5},
            "workflow_catalog_meta": {"schema_version": 1, "delivery": "monolith"},
        }
        with patch(
            "app.mod_sdk.host_profile.build_host_profile_api_payload",
            return_value=payload,
        ):
            r = client.get("/api/system/host-profile")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["profile"]["sku"] == "enterprise"
        assert body["data"]["industry_presets_meta"]["preset_count"] == 5


# ── get_industry_presets deep ───────────────────────────────────────────────


class TestGetIndustryPresetsDeep:
    def test_empty_presets(self, client: TestClient) -> None:
        doc = {"schema_version": 1, "presets": {}}
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            return_value=doc,
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["presets"] == {}
        assert body["data"]["preset_ids"] == []

    def test_no_presets_key(self, client: TestClient) -> None:
        doc = {"schema_version": 1}
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            return_value=doc,
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["presets"] == {}
        assert body["data"]["preset_ids"] == []

    def test_presets_none(self, client: TestClient) -> None:
        doc = {"schema_version": 1, "presets": None}
        with patch(
            "app.mod_sdk.host_profile.load_industry_presets_document",
            return_value=doc,
        ):
            r = client.get("/api/system/industry-presets")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["presets"] == {}
        assert body["data"]["preset_ids"] == []


# ── get_workflow_employee_catalog deep ──────────────────────────────────────


class TestGetWorkflowEmployeeCatalogDeep:
    def test_with_split_delivery(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.host_profile.scan_workflow_employee_catalog_from_mods",
                return_value={"items": ["a", "b"]},
            ),
            patch(
                "app.mod_sdk.host_profile.load_host_profile",
                return_value={
                    "workflow_delivery": "split",
                    "workflow_monolith_mod_id": "m1",
                    "workflow_split_mod_ids": ["s1", "s2"],
                },
            ),
            patch(
                "app.mod_sdk.host_profile.load_workflow_employee_catalog",
                return_value={"static": True},
            ),
        ):
            r = client.get("/api/system/workflow-employee-catalog")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["workflow_delivery"] == "split"
        assert body["data"]["workflow_split_mod_ids"] == ["s1", "s2"]

    def test_missing_workflow_fields(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.host_profile.scan_workflow_employee_catalog_from_mods",
                return_value={},
            ),
            patch(
                "app.mod_sdk.host_profile.load_host_profile",
                return_value={},  # no workflow fields
            ),
            patch(
                "app.mod_sdk.host_profile.load_workflow_employee_catalog",
                return_value={},
            ),
        ):
            r = client.get("/api/system/workflow-employee-catalog")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["workflow_delivery"] is None
        assert body["data"]["workflow_monolith_mod_id"] is None
        assert body["data"]["workflow_split_mod_ids"] is None


# ── get_employee_registry_rules deep ────────────────────────────────────────


class TestGetEmployeeRegistryRulesDeep:
    def test_with_complex_rules(self, client: TestClient) -> None:
        rules = {
            "workflow_employee_id_prefixes": ["prefix1-", "prefix2-"],
            "exclude_id_suffixes": ["-bridge", "-test"],
            "exclude_artifact_types": ["employee_pack"],
            "exclude_mod_ids": ["mod1", "mod2"],
            "non_workflow_desk_employee_patterns": ["^pattern1$", "^pattern2$"],
        }
        with patch(
            "app.mod_sdk.host_profile.get_employee_registry_rules",
            return_value=rules,
        ):
            r = client.get("/api/system/employee-registry-rules")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["workflow_employee_id_prefixes"] == ["prefix1-", "prefix2-"]
        assert body["data"]["exclude_mod_ids"] == ["mod1", "mod2"]

    def test_empty_rules(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.host_profile.get_employee_registry_rules",
            return_value={},
        ):
            r = client.get("/api/system/employee-registry-rules")
        assert r.status_code == 200
        assert r.json()["data"] == {}


# ── _build_industry_response deep ───────────────────────────────────────────


class TestBuildIndustryResponseDeep:
    def test_with_custom_profile(self) -> None:
        profile = _make_profile(
            name="自定义",
            units={"个": {"abbr": "g"}},
            quantity_fields={"primary_field": "count"},
            product_fields={"name": "product_name", "code": "product_code"},
            order_types={"shipment": "发货", "purchase": "采购"},
            print_config={"template": "custom", "paper": "A4"},
        )
        out = _build_industry_response("custom", profile)
        assert out["id"] == "custom"
        assert out["name"] == "自定义"
        assert out["config"]["units"] == {"个": {"abbr": "g"}}
        assert out["config"]["print_config"]["paper"] == "A4"

    def test_with_none_values_in_profile(self) -> None:
        """Profile with None values for some fields."""
        profile = SimpleNamespace(
            name="test",
            units=None,
            quantity_fields=None,
            product_fields=None,
            order_types=None,
            print_config=None,
        )
        out = _build_industry_response("test", profile)
        assert out["config"]["units"] is None
        assert out["config"]["quantity_fields"] is None
