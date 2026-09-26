from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.enterprise import private_delivery_binding as binding
from app.mod_sdk import customer_delivery, customer_features


def test_private_delivery_keeps_customer_identity_and_separate_runtime():
    assert "taiyangniao-pro" in customer_delivery.list_account_custom_mod_ids()
    row = customer_delivery.delivery_for_account("SUNBIRD")
    assert row["delivery_mode"] == "private_mod"
    assert row["runtime_mod_id"] == "sunbird-attendance-custom"
    assert (
        customer_delivery.account_custom_mod_ids_for_industry("饰品包装", {"attendance-industry"})
        == []
    )
    assert customer_delivery.account_custom_mod_ids_for_industry(
        "饰品包装", {"taiyangniao-pro"}
    ) == ["taiyangniao-pro"]
    assert (
        customer_delivery.delivery_seed_package_for_mod(
            "attendance-industry", account_username="OTHER"
        )
        is None
    )
    assert (
        customer_delivery.delivery_seed_package_for_mod(
            "attendance-industry", account_username="SUNBIRD"
        )
        is None
    )
    assert customer_delivery.delivery_seed_package_for_mod(
        "sunbird-attendance-custom", account_username="SUNBIRD"
    )
    assert (
        customer_delivery.delivery_seed_package_for_mod(
            "sunbird-attendance-custom", account_username="OTHER"
        )
        is None
    )


@pytest.mark.parametrize("row_kind", ["missing", "expired", "other", "malformed"])
def test_binding_never_inherits_another_accounts_global_cache(monkeypatch, row_kind):
    row = SimpleNamespace(
        expires_at=datetime.now(UTC) + timedelta(days=1),
        market_user_id=61,
        company_brand="SUNBIRD",
        impersonating_username="",
        entitled_mod_ids_json='["coating-industry"]',
    )
    if row_kind == "expired":
        row.expires_at -= timedelta(days=2)
    if row_kind == "malformed":
        row.entitled_mod_ids_json = "{}"
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (
        None if row_kind == "missing" else row
    )

    @contextmanager
    def database():
        yield db

    monkeypatch.setattr(binding.entitlements, "_session_row_db_context", database)
    monkeypatch.setattr(binding.entitlements, "_cached_market_user_id", 29)
    monkeypatch.setattr(binding.entitlements, "_cached_market_username", "SUNBIRD")
    monkeypatch.setattr(
        binding.entitlements, "get_cached_entitled_client_mod_ids", lambda: {"taiyangniao-pro"}
    )
    monkeypatch.setattr(
        binding.entitlements, "_session_username_for_entitlements", lambda _: "OTHER"
    )
    result = binding.load_session_private_delivery_binding("request-session")
    assert "taiyangniao-pro" not in result["mod_ids"]
    assert result["username"] != "SUNBIRD"
    assert result["market_user_id"] != 29
    if row_kind == "other":
        assert result["mod_ids"] == {"coating-industry"}


@pytest.mark.parametrize(
    "username,mods,status",
    [
        ("SUNBIRD", {"taiyangniao-pro", "attendance-industry"}, 200),
        ("SUNBIRD", {"attendance-industry"}, 403),
        ("OTHER", {"taiyangniao-pro", "attendance-industry"}, 403),
        ("", set(), 403),
    ],
)
def test_conversion_requires_both_account_and_custom_entitlement(
    monkeypatch, username, mods, status
):
    monkeypatch.setattr(customer_features, "get_logged_in_user", lambda _: object())
    monkeypatch.setattr(
        customer_features,
        "load_session_private_delivery_binding",
        lambda _: {
            "username": username,
            "market_user_id": 29,
            "mod_ids": mods,
        },
    )
    app = FastAPI()
    app.add_api_route("/capabilities", customer_features.attendance_custom_features)
    app.add_api_route("/conversion", customer_features.require_attendance_conversion)
    with TestClient(app) as client:
        assert client.get("/conversion").status_code == status
        features = client.get("/capabilities").json()["custom_features"]
        assert ("attendance-convert" in features) == (status == 200)


def test_legacy_endpoints_reject_unauthenticated_requests(monkeypatch):
    from app.legacy.routes.taiyangniao_attendance_compat import router

    def deny(_):
        raise HTTPException(status_code=401)

    monkeypatch.setattr(customer_features, "get_logged_in_user", deny)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        for method, path in [("get", "rules"), ("get", "download"), ("post", "convert-upload")]:
            assert (
                getattr(client, method)(f"/api/mod/taiyangniao-pro/attendance/{path}").status_code
                == 401
            )


def test_attendance_file_owner_binds_tenant_and_local_user(monkeypatch):
    from starlette.requests import Request

    from app.mod_sdk import attendance_artifacts as artifacts

    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(artifacts, "get_logged_in_user", lambda _: SimpleNamespace(id=7))
    monkeypatch.setattr(artifacts, "resolve_workspace_owner_id", lambda *_: "tenant:11")
    assert artifacts.owner_for_request(request) == "tenant:11|user:7"
    monkeypatch.setattr(artifacts, "resolve_workspace_owner_id", lambda *_: "tenant:22")
    assert artifacts.owner_for_request(request) == "tenant:22|user:7"
    with pytest.raises(ValueError):
        artifacts.owner_for_user_id(7, "untrusted")


def test_shared_runtime_conversion_routes_are_all_guarded(monkeypatch, tmp_path):
    import importlib.util
    import logging
    import sys
    from pathlib import Path

    from fastapi import APIRouter

    path = (
        Path(__file__).resolve().parents[2]
        / "XCAGI/mods/attendance-industry/backend/attendance_routes.py"
    )
    spec = importlib.util.spec_from_file_location("custom_conversion_routes_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(
        sys.modules,
        "attendance_engine.convert",
        SimpleNamespace(convert_attendance_file=lambda: None),
    )
    monkeypatch.setattr(customer_features, "get_logged_in_user", lambda _: object())
    monkeypatch.setattr(customer_features, "load_session_private_delivery_binding", lambda _: {})
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.get_logged_in_user", lambda _: SimpleNamespace(id=99)
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install", lambda _: None
    )
    router = APIRouter()
    module.register(
        router,
        logger=logging.getLogger(__name__),
        get_database_path=lambda: tmp_path / "empty.db",
        DEFAULT_TEMPLATE_RELPATH="424/template.xlsx",
        _normalize_relpath=lambda x: x,
        _resolve_personnel_roster=lambda: [],
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/attendance/capabilities").json()["custom_features"] == []
        for method, path in [
            ("get", "rules"),
            ("get", "policy"),
            ("post", "policy"),
            ("post", "convert-upload"),
            ("get", "download"),
        ]:
            assert getattr(client, method)(f"/attendance/{path}").status_code == 403


@pytest.mark.parametrize(
    "relative_path",
    [
        "XCAGI/mods/attendance-industry/backend/attendance_routes.py",
        "mods/taiyangniao-pro/backend/attendance_routes.py",
        "XCAGI/mods/taiyangniao-pro/backend/attendance_routes.py",
    ],
)
def test_attendance_download_is_limited_to_current_user_outputs(
    monkeypatch, tmp_path, relative_path
):
    import importlib.util
    import logging
    import sys
    from pathlib import Path

    from fastapi import APIRouter

    from app.mod_sdk.attendance_artifacts import allocate_file, owner_for_user_id

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    database = tmp_path / "data" / "xcagi.db"
    database.parent.mkdir()
    database.write_bytes(b"private database")
    own_owner = owner_for_user_id(1, "tenant:11")
    own_output = allocate_file(own_owner, "output")
    own_output.write_bytes(b"own result")
    other_output = allocate_file(owner_for_user_id(2, "tenant:11"), "output")
    other_output.write_bytes(b"other result")
    other_tenant_output = allocate_file(owner_for_user_id(1, "tenant:22"), "output")
    other_tenant_output.write_bytes(b"other tenant result")

    path = Path(__file__).resolve().parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(
        f"attendance_download_test_{path.parent.parent.name}", path
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules,
        "attendance_engine.convert",
        SimpleNamespace(convert_attendance_file=lambda *_a, **_k: {}),
    )
    if "taiyangniao-pro" in relative_path:
        from app.mod_sdk import attendance

        monkeypatch.setattr(attendance, "ensure_attendance_engine_on_path", lambda: None)
    spec.loader.exec_module(module)
    router = APIRouter()
    module.register(
        router,
        logger=logging.getLogger(__name__),
        get_database_path=lambda: tmp_path / "empty.db",
        DEFAULT_TEMPLATE_RELPATH="424/template.xlsx",
        _normalize_relpath=lambda value, **_kwargs: value,
        _resolve_personnel_roster=lambda *_args: [],
    )
    app = FastAPI()
    app.dependency_overrides[module.owner_for_request] = lambda: own_owner
    if "attendance-industry" in relative_path:
        app.dependency_overrides[module.require_attendance_conversion] = lambda: None
    app.include_router(router)

    with TestClient(app) as client:
        endpoint = "/attendance/download"
        assert client.get(endpoint, params={"relpath": own_output.name}).content == b"own result"
        assert client.get(endpoint, params={"relpath": other_output.name}).status_code == 404
        assert client.get(endpoint, params={"relpath": other_tenant_output.name}).status_code == 404
        assert client.get(endpoint, params={"relpath": "data/xcagi.db"}).status_code == 400


@pytest.mark.asyncio
async def test_private_delivery_does_not_count_shared_install_as_custom_delivery(
    monkeypatch, tmp_path
):
    __import__("app.fastapi_routes.mod_store_routes")
    from starlette.requests import Request

    from app.application import private_mod_delivery_app as state
    from app.fastapi_routes import private_mod_delivery_routes as routes

    monkeypatch.setattr(state, "_state_path", lambda: tmp_path / "delivery.json")
    monkeypatch.setattr(
        routes,
        "_private_mod_context",
        AsyncMock(
            return_value={
                "mod_ids": {"taiyangniao-pro"},
                "market_user_id": 29,
                "username": "SUNBIRD",
            }
        ),
    )
    monkeypatch.setattr(routes, "_market_token", AsyncMock(return_value=""))
    monkeypatch.setattr(
        routes,
        "_private_mod_local_rows",
        lambda ids: {
            "attendance-industry": {
                "id": "attendance-industry",
                "name": "通用考勤模块",
                "version": "1.0.0",
            },
        },
    )
    response = await routes.mod_store_private_delivery(Request({"type": "http", "headers": []}))
    project = response.data["projects"][0]
    assert project["mod_id"] == "taiyangniao-pro"
    assert project["runtime_mod_id"] == "sunbird-attendance-custom"
    assert project["installed"] is False
    assert project["update_source"] == "unavailable"
    assert project["update_available"] is False
    assert project["overall_status"] != "delivered"
    assert "attendance-convert" in str(project["track_nodes"])


@pytest.mark.asyncio
async def test_legacy_entitlement_updates_only_the_separate_owner_bound_runtime(monkeypatch):
    __import__("app.fastapi_routes.mod_store_routes")
    from starlette.requests import Request

    from app.fastapi_routes import private_mod_delivery_progress_routes as routes

    monkeypatch.setattr(
        routes, "_request_payload", AsyncMock(return_value={"mod_id": "taiyangniao-pro"})
    )
    monkeypatch.setattr(
        routes, "_private_mod_context", AsyncMock(return_value={"mod_ids": {"taiyangniao-pro"}})
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.get_logged_in_user", lambda _: SimpleNamespace(id=99)
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.session_id_from_request", lambda _: "fixture-session"
    )
    monkeypatch.setattr(
        "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
        lambda *_: "tenant:fixture",
    )
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        AsyncMock(return_value="fixture-token"),
    )
    update = AsyncMock(return_value={"success": True, "message": "已安装"})
    monkeypatch.setattr(
        "app.application.private_mod_delivery_app.update_private_mod_from_library", update
    )
    result = await routes.mod_store_private_mod_update(Request({"type": "http", "headers": []}))
    assert result.success is True
    update.assert_awaited_once_with(
        "sunbird-attendance-custom",
        "fixture-token",
        expected_version="",
        owner_scope="tenant:fixture",
    )
