"""Navigation parity and account/installed-Mod boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.fastapi_routes.mobile_extensions.navigation_constants import resolve_mobile_navigation

ROOT = Path(__file__).resolve().parents[2]


def _menu(mods=(), **kwargs):
    return {
        row["key"]: row
        for row in resolve_mobile_navigation(
            list(mods), account_kind=kwargs.pop("account_kind", "enterprise"), **kwargs
        )
    }


def _installed(relative):
    manifest = json.loads((ROOT / "mods" / relative / "manifest.json").read_text())
    return {
        **manifest,
        "frontend_menu": manifest["frontend"].get("menu", []),
        "menu_overrides": manifest["frontend"].get("menu_overrides", []),
    }


def test_host_navigation_uses_desktop_catalog_without_uninstalled_business_pages():
    menu = _menu()
    assert menu["employee-workflow"]["path"] == "/employee-workbench"
    assert menu["persy-knowledge"]["path"] == "/persy/knowledge"
    assert menu["business-docking"]["mobile_group"] == "data"
    assert menu["ai-ecosystem"]["path"] == "/ai-ecosystem"
    assert (
        not {"products", "inventory", "purchase", "approval-hub", "admin-entitlements"}
        & menu.keys()
    )


@pytest.mark.parametrize("industry", [None, [], "invalid", {"subsystems": None}])
def test_malformed_industry_metadata_does_not_create_business_slots(industry):
    assert _menu([{"id": "custom", "industry": industry}]) == _menu()


def test_personal_and_admin_roles_remain_distinct():
    assert set(_menu(account_kind="personal")) == {"chat", "im", "ai-ecosystem", "settings"}
    assert "admin-entitlements" in _menu(account_kind="admin")
    fake_admin = {"id": "custom", "frontend_menu": [{"id": "admin-entitlements"}]}
    assert "admin-entitlements" not in _menu([fake_admin])


def test_employee_child_alias_uses_the_existing_workspace_entry():
    menu = _menu([{"id": "office", "frontend_menu": [{"id": "workflow-employee-space"}]}])
    assert menu["employee-workflow"]["path"] == "/employee-workbench"
    assert "mod-workflow-employee-space" not in menu


def test_installed_bridge_menus_get_shared_keys_groups_and_browsable_templates():
    menu = _menu(
        [
            _installed("bridge/xcagi-erp-domain-bridge"),
            _installed("bridge/xcagi-approval-bridge"),
            _installed("tools/kellai"),
        ]
    )
    assert menu["purchase"]["mobile_group"] == "business"
    assert menu["materials"]["mobile_group"] == "data"
    assert menu["data-sources"]["mobile_group"] == "data"
    assert menu["data-sources"]["path"] == "/kellai"
    assert menu["data-sources"]["mod_id"] == "kellai"
    assert menu["approval-hub"]["mobile_group"] == "tasks"
    for key in ("print", "printer-list", "template-preview"):
        assert menu[key]["mobile_group"] == "computer"
        assert menu[key]["requires_desktop"] is False
    assert menu["template-preview"]["mod_id"] == "xcagi-erp-domain-bridge"
    assert "business-docking" in menu


def test_kellai_navigation_requires_its_module_and_uses_tenant_destination():
    assert "data-sources" not in _menu([_installed("bridge/xcagi-erp-domain-bridge")])
    menu = _menu([_installed("tools/kellai")], tenant=True, tenant_member=True)
    assert menu["data-sources"]["path"] == "/mod/kellai/workspace"
    assert menu["data-sources"]["name"] == "客来来"


def test_tenant_routes_require_authorized_owner_mod_and_elt_permission():
    industry = {"id": "industry", "industry": {"subsystems": {"inventory": {"label": "库存"}}}}
    assert set(_menu([industry], tenant=True, tenant_member=True)) == {"settings"}
    menu = _menu(
        [industry, _installed("bridge/xcagi-erp-domain-bridge")],
        tenant=True,
        tenant_member=True,
        permissions=["elt.read"],
    )
    assert menu["inventory"]["path"] == "/mod/xcagi-erp-domain-bridge/inventory"
    assert menu["business-docking"]["path"] == "/business-docking"
    assert not {"chat", "employee-workflow", "admin-entitlements"} & menu.keys()
    assert all(
        row["path"].startswith("/mod/")
        for key, row in menu.items()
        if key not in {"settings", "business-docking"}
    )


def test_hidden_external_and_unentitled_mod_destinations_are_not_exposed():
    mod = {
        "id": "custom",
        "frontend_menu": [
            {"id": "hidden", "hidden": True},
            {"id": "other", "path": "/mod/unlicensed/page"},
            {"id": "external", "path": "https://example.com"},
            {"id": "malformed", "path": "http://["},
            {"id": "admin-alias", "path": "/admin-entitlements?tab=users"},
            {"id": "escape", "path": "/mod/custom/%2e%2e/unlicensed"},
            {"id": "execute", "mobile_group": "computer", "requires_desktop": True},
        ],
    }
    menu = _menu([mod])
    assert (
        not {
            "mod-hidden",
            "mod-other",
            "mod-external",
            "mod-escape",
            "mod-malformed",
            "mod-admin-alias",
            "admin-entitlements",
        }
        & menu.keys()
    )
    assert menu["mod-execute"]["requires_desktop"] is True
    assert menu["mod-execute"]["mobile_group"] == "computer"


def test_tenant_founder_keeps_core_workspaces_and_scoped_business_paths():
    menu = _menu([_installed("bridge/xcagi-erp-domain-bridge")], tenant=True)
    assert {"employee-workflow", "ai-ecosystem", "persy-knowledge"} <= menu.keys()
    assert menu["products"]["path"] == "/mod/xcagi-erp-domain-bridge/products"


@pytest.mark.asyncio
@pytest.mark.parametrize("session_meta", [None, {"account_kind": "enterprise"}])
async def test_endpoint_loads_current_session_grants_before_listing_mods(monkeypatch, session_meta):
    from app.enterprise import mod_entitlements as grants
    from app.fastapi_routes.mobile_extensions.routes_workspace import WorkspaceRoutes

    mods = [{"id": key, "frontend_menu": [{"id": key}]} for key in ("customer-one", "customer-two")]

    async def sync(sid):
        grants.set_session_entitlements(
            market_user_id=1, market_username=sid, entitled_client_mod_ids={sid}
        )

    monkeypatch.setattr(grants, "sync_entitlements_for_session", sync)
    monkeypatch.setattr(grants, "enterprise_mod_filter_active", lambda: True)
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: session_meta,
    )
    ports = SimpleNamespace(
        mobile_session_id_from_request=lambda request: request.headers["x-session-id"],
        mobile_mod_items=lambda: [
            mod for mod in mods if mod["id"] in grants.get_cached_entitled_client_mod_ids()
        ],
    )
    route = WorkspaceRoutes(ports, lambda: None).mobile_nav_menu
    with grants.request_entitlement_scope():
        for current in ("customer-one", "customer-two"):
            request = Request({"type": "http", "headers": [(b"x-session-id", current.encode())]})
            result = await route(
                request,
                user=SimpleNamespace(
                    id=1,
                    role="user",
                    tier="personal" if session_meta else "enterprise",
                    tenant_id=7,
                ),
            )
            assert result["data"]["account_kind"] == "enterprise"
            assert "employee-workflow" in {item["key"] for item in result["data"]["items"]}
            actual = {item["mod_id"] for item in result["data"]["items"] if item["source"] == "mod"}
            assert actual == {current}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,kind",
    [
        ("personal", "personal"),
        ("enterprise", "enterprise"),
        ("admin", "admin"),
        ("super_admin", "admin"),
        ("owner", "admin"),
    ],
)
async def test_endpoint_role_and_failed_mod_lookup_fallback(role, kind):
    from app.fastapi_routes.mobile_extensions.routes_workspace import WorkspaceRoutes

    def unavailable():
        raise OSError("offline")

    route = WorkspaceRoutes(
        SimpleNamespace(
            mobile_session_id_from_request=lambda request: "", mobile_mod_items=unavailable
        ),
        lambda: None,
    ).mobile_nav_menu
    request = Request({"type": "http", "headers": []})
    assert (await route(request, user=None)).status_code == 401
    result = await route(request, user=SimpleNamespace(id=1, role=role))
    assert result["data"]["account_kind"] == kind
    actual = {item["key"] for item in result["data"]["items"]}
    assert ("admin-entitlements" in actual) == (kind == "admin")
    assert ("employee-workflow" in actual) == (kind != "personal")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal,grants", [("user", ["elt.read"]), ("user", []), ("error", []), ("unknown", [])]
)
async def test_tenant_endpoint_requires_typed_user_and_current_permissions(
    monkeypatch, principal, grants
):
    from app.db.models import User
    from app.fastapi_routes.mobile_extensions.routes_workspace import WorkspaceRoutes

    calls = []
    user = (SimpleNamespace if principal == "unknown" else User)(
        id=23, role="tenant:7:operator", tenant_id=7, tier="enterprise"
    )

    def permissions(actual):
        calls.append(actual)
        if principal == "error":
            raise OSError("permission storage unavailable")
        return grants

    monkeypatch.setattr(
        "app.application.auth_app_service.get_auth_app_service",
        lambda: SimpleNamespace(get_user_permissions=permissions),
    )
    route = WorkspaceRoutes(
        SimpleNamespace(mobile_session_id_from_request=lambda _: "", mobile_mod_items=lambda: []),
        lambda: None,
    ).mobile_nav_menu
    result = await route(Request({"type": "http", "headers": []}), user=user)
    keys = {item["key"] for item in result["data"]["items"]}
    assert keys == ({"settings", "business-docking"} if grants else {"settings"})
    assert calls == ([] if principal == "unknown" else [user])
