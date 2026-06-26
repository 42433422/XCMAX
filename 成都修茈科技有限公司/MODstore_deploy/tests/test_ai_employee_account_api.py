"""AI 员工账号管理 API：路由挂载与权限。"""

from __future__ import annotations

import types

from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.deps import get_current_user


def _new_client(tmp_path, monkeypatch):
    import pytest

    try:
        import modstore_server.ai_employee_account_api  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"ai_employee_account_api not importable (missing dep): {exc}")

    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "ai_employee_accounts.sqlite"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = create_app(load_default_config())
    client = TestClient(app)
    return app, client


def test_ai_accounts_list_route_exists_requires_auth(tmp_path, monkeypatch):
    _, client = _new_client(tmp_path, monkeypatch)
    r = client.get("/api/admin/ai-accounts")
    assert r.status_code != 404
    assert r.status_code == 401


def test_ai_accounts_list_requires_admin(tmp_path, monkeypatch):
    app, client = _new_client(tmp_path, monkeypatch)
    user = types.SimpleNamespace(id=1, username="u", is_admin=False, email="u@u")
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = client.get("/api/admin/ai-accounts")
        assert r.status_code != 404
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
