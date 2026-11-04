import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.engine import make_url


def test_postgres_active_mod_database_url_suffix(monkeypatch):
    from app import db
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:secret@localhost:5432/xcagi")
    monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", "1")

    token = set_request_active_mod_id("leshan-kc-ai-suite-test")
    try:
        url = db._get_database_url()
    finally:
        reset_request_active_mod_id(token)

    parsed = make_url(url)
    assert parsed.database == "xcagi__leshan_kc_ai_suite_test"
    assert "secret" in parsed.render_as_string(hide_password=False)


def test_session_factories_are_cached_per_resolved_database_url(monkeypatch, tmp_path):
    from app import db
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    db.dispose_and_recreate_engine()
    base_path = tmp_path / "xcagi.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{base_path}")
    monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", "1")
    monkeypatch.delenv("XCAGI_MOD_DATABASE_URLS", raising=False)

    base_factory = db._get_session_local()

    token = set_request_active_mod_id("taiyangniao-pro")
    try:
        mod_factory = db._get_session_local()
        mod_url = db._get_database_url()
    finally:
        reset_request_active_mod_id(token)

    base_factory_again = db._get_session_local()

    assert base_factory_again is base_factory
    assert mod_factory is not base_factory
    assert Path(make_url(mod_url).database or "").name == "xcagi__taiyangniao_pro.db"

    db.dispose_and_recreate_engine()


@pytest.mark.parametrize(
    "path,headers,active_mod",
    [
        ("/api/mod/leshan-kc-ai-suite-test/status", [], "leshan-kc-ai-suite-test"),
        ("/api/mod/path-mod/status", [(b"x-xcagi-active-mod-id", b"header-mod")], "header-mod"),
    ],
    ids=["infers_active_mod_from_api_path", "header_takes_priority_over_path"],
)
def test_mod_context_middleware_routes_ready_mod(monkeypatch, path, headers, active_mod):
    from app.infrastructure.mods.mod_auth import ModContextMiddleware
    from app.request_active_mod_ctx import get_request_active_mod_id

    # Context routing requires a successfully authorized, loaded Mod.
    ready = Mock(return_value=True)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active", lambda: False
    )
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", ready)
    seen: dict[str, str] = {}
    sent = []

    async def downstream(scope, receive, send):
        seen["active_mod"] = get_request_active_mod_id()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    asyncio.run(ModContextMiddleware(downstream)(scope, receive, send))

    ready.assert_called_once_with(active_mod, session_id=None, requires_http=True)
    assert sent[0]["status"] == 200
    assert seen["active_mod"] == active_mod
    assert get_request_active_mod_id() == ""


def test_mod_context_middleware_survives_stale_session_with_active_mod_header(monkeypatch):
    """过期 session 的 Mod 校验异常须返回 503，且不得继续执行宿主 API。"""
    from app.infrastructure.mods.mod_auth import ModContextMiddleware
    from app.request_active_mod_ctx import get_request_active_mod_id

    reached = []

    async def downstream(scope, receive, send):
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    failed_ready = Mock(side_effect=RuntimeError("simulated entitlement restore failure"))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
        failed_ready,
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/platform-shell/capabilities",
        "headers": [
            (b"x-xcagi-active-mod-id", b"xcagi-workflow-visualization-bridge"),
            (b"cookie", b"session_id=stale-invalid-session"),
        ],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }

    asyncio.run(ModContextMiddleware(downstream)(scope, receive, send))

    failed_ready.assert_called_once_with(
        "xcagi-workflow-visualization-bridge",
        session_id="stale-invalid-session",
        requires_http=False,
    )
    assert sent[0]["status"] == 503
    assert b'"error":"mod_unavailable"' in sent[1]["body"]
    assert reached == []
    assert get_request_active_mod_id() == ""
