"""演示企业号 · 市场登录路径（官网 vs 本地 shim）。"""

from __future__ import annotations

import secrets

import pytest
from fastapi.responses import JSONResponse


@pytest.fixture
def demo_password(monkeypatch):
    password = secrets.token_urlsafe(32)
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", password)
    return password


@pytest.mark.asyncio
async def test_远端市场演示号走真实_api_不用本地_shim(monkeypatch, demo_password):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    login_calls: list[str] = []

    async def proxy_router(method, path, **kwargs):
        login_calls.append(path)
        if path == "/api/auth/me":
            return {
                "id": 33,
                "username": "xcagi-enterprise-demo",
                "is_enterprise": True,
                "is_admin": False,
            }
        return {
            "success": True,
            "access_token": "remote-token",
            "refresh_token": "remote-refresh",
            "user": {
                "id": 33,
                "username": "xcagi-enterprise-demo",
                "is_enterprise": True,
                "is_admin": False,
            },
        }

    monkeypatch.setattr(mod, "_proxy_json", proxy_router)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", demo_password)

    assert result["success"] is True
    assert result["token"] == "remote-token"
    assert result["is_enterprise"] is True
    assert result["market_base_url"] == "https://xiu-ci.com"
    assert "/api/auth/login" in login_calls


@pytest.mark.asyncio
async def test_本地市场优先_demo_shim(monkeypatch, demo_password):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://127.0.0.1:8788")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    async def proxy_router(method, path, **kwargs):
        return {
            "success": True,
            "access_token": "local-market-token",
            "refresh_token": "local-refresh",
            "user": {
                "id": 3,
                "username": "xcagi-enterprise-demo",
                "is_enterprise": True,
                "is_admin": False,
            },
        }

    monkeypatch.setattr(mod, "_proxy_json", proxy_router)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", demo_password)

    assert result["success"] is True
    assert result["token"] == "local-market-token"
    assert result["is_enterprise"] is True
    assert result["is_market_admin"] is False
    assert result["market_base_url"] == "http://127.0.0.1:8788"


@pytest.mark.asyncio
async def test_本地市场不可达时_demo_shim_兜底(monkeypatch, demo_password):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://127.0.0.1:8788")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    async def unreachable(*args, **kwargs):
        return JSONResponse(
            {"success": False, "message": "无法连接修茈市场服务器：ConnectError"},
            status_code=502,
        )

    monkeypatch.setattr(mod, "_proxy_json", unreachable)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", demo_password)

    assert result["success"] is True
    assert str(result["token"]).startswith("xcagi-local-surface-audit-demo")


@pytest.fixture
def isolated_demo(monkeypatch, tmp_path):
    from app.application import surface_audit_demo_account as demo

    for key in (
        "SURFACE_AUDIT_DEMO_PASSWORD",
        "SURFACE_AUDIT_ENTERPRISE_PASSWORD",
        "SURFACE_AUDIT_DEMO_USER",
        "SURFACE_AUDIT_ENTERPRISE_USER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(demo, "_CONFIG_PATH", tmp_path / "demo.json")
    demo.demo_account_config.cache_clear()
    yield demo
    demo.demo_account_config.cache_clear()


@pytest.mark.parametrize("config", [None, "{}", '{"password":""}', '{"password":"  "}', "invalid"])
def test_missing_password_disables_demo_without_database_access(isolated_demo, config):
    demo = isolated_demo
    if config is not None:
        demo._CONFIG_PATH.write_text(config)
    assert demo.demo_password() == ""
    assert not demo.credentials_match_demo(demo.demo_username(), "")
    assert demo.try_local_demo_market_login(demo.demo_username(), secrets.token_urlsafe()) is None

    def forbidden_database():
        pytest.fail("Disabled demo must not access the database")

    demo.seed_demo_user_row(session_factory=forbidden_database)


@pytest.mark.parametrize(
    "source", ["SURFACE_AUDIT_DEMO_PASSWORD", "SURFACE_AUDIT_ENTERPRISE_PASSWORD", "config"]
)
def test_explicit_password_preserves_non_admin_demo(isolated_demo, monkeypatch, source):
    import json

    demo = isolated_demo
    password = secrets.token_urlsafe(32)
    if source == "config":
        demo._CONFIG_PATH.write_text(json.dumps({"password": password}))
    else:
        monkeypatch.setenv(source, password)
    assert demo.demo_password() == password
    assert not demo.credentials_match_demo(demo.demo_username(), "")
    assert not demo.credentials_match_demo(demo.demo_username(), secrets.token_urlsafe(32))
    assert not demo.credentials_match_demo("another-user", password)
    result = demo.try_local_demo_market_login(demo.demo_username(), password)
    assert result["is_enterprise"] is True
    assert result["is_market_admin"] is False
    assert result["raw"]["user"]["is_admin"] is False


def test_env_precedence_and_blank_disable(isolated_demo, monkeypatch):
    import json

    demo = isolated_demo
    primary, secondary, configured = (secrets.token_urlsafe(32) for _ in range(3))
    demo._CONFIG_PATH.write_text(json.dumps({"password": configured}))
    monkeypatch.setenv("SURFACE_AUDIT_ENTERPRISE_PASSWORD", secondary)
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", primary)
    assert demo.demo_password() == primary
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", "   ")
    assert not demo.credentials_match_demo(demo.demo_username(), "")


def test_audit_exception_does_not_invent_password(isolated_demo, monkeypatch):
    from app.application import surface_audit_service as audit

    monkeypatch.delenv("SURFACE_AUDIT_USER", raising=False)
    monkeypatch.delenv("SURFACE_AUDIT_PASSWORD", raising=False)
    monkeypatch.setattr(audit, "_adb_has_device", lambda: False)

    def unavailable():
        raise ValueError("Unavailable configuration")

    monkeypatch.setattr(isolated_demo, "demo_password", unavailable)
    assert audit._node_env("P-S")["SURFACE_AUDIT_PASSWORD"] == ""


def test_archived_seed_excluded_from_image_and_active_migrations():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).parents[1]
    scripts = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert "2026_06_06_surface_audit_demo" not in {r.revision for r in scripts.walk_revisions()}
    assert (
        "alembic/versions/_archive_pre_baseline_2026_06_22/"
        in (root / ".dockerignore").read_text().splitlines()
    )


def test_configured_seed_preserves_normal_users_and_existing_demo_when_disabled(
    isolated_demo, monkeypatch
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.db_base import Base
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.utils.security.password_hash import check_password_hash, generate_password_hash

    demo = isolated_demo
    password, normal_password = (secrets.token_urlsafe(32) for _ in range(2))
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as db:
            db.add(
                User(
                    username="normal-user",
                    password=generate_password_hash(normal_password),
                    role="user",
                )
            )
            db.commit()
        monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", password)
        demo.seed_demo_user_row(session_factory=sessions)
        monkeypatch.delenv("SURFACE_AUDIT_DEMO_PASSWORD")
        demo.seed_demo_user_row(session_factory=sessions)
        with sessions() as db:
            row = db.query(User).filter_by(username=demo.demo_username()).one()
            assert row.role == "user"
            assert check_password_hash(row.password, password)
            assert db.query(Tenant).filter_by(id=row.tenant_id).one().plan_id == "saas-enterprise"
            normal = db.query(User).filter_by(username="normal-user").one()
            assert normal.role == "user" and normal.tenant_id is None
            assert check_password_hash(normal.password, normal_password)
    finally:
        engine.dispose()
