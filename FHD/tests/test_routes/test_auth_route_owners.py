"""Domain routers retain dependency gates and resolve only their supplied services."""

import importlib.abc
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.db.models.user import User
from app.fastapi_routes.domains.auth.administration_routes import AdministrationRoutes
from app.fastapi_routes.domains.auth.profile_routes import ProfileRoutes
from app.fastapi_routes.domains.auth.session_routes import SessionRoutes


def test_auth_package_loads_compatibility_routes_only_when_requested(monkeypatch):
    name = "_auth_domain_export_test"
    root_name = f"{name}.auth_routes"  # debt19: routes.py → auth_routes.py; package.routes still lazy-loads
    loaded = []

    class SyntheticRoutes(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == root_name:
                return importlib.util.spec_from_loader(fullname, self)
            return None

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            loaded.append(module.__name__)
            module.router = object()

    source = Path(__file__).resolve().parents[2] / "app/fastapi_routes/domains/auth/__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, source, submodule_search_locations=[str(source.parent)]
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setattr(sys, "meta_path", [SyntheticRoutes(), *sys.meta_path])
    try:
        spec.loader.exec_module(package)
        assert loaded == [] and root_name not in sys.modules
        routes = package.routes
        assert loaded == [root_name]
        assert package._routes is routes and package.routes is routes
        with pytest.raises(AttributeError):
            _ = package.unregistered_export
    finally:
        sys.modules.pop(root_name, None)


def test_session_router_instances_keep_independent_late_service_factories():
    first = Mock(return_value=SimpleNamespace(current_user=lambda request: {"session": "first"}))
    second = Mock(return_value=SimpleNamespace(current_user=lambda request: {"session": "second"}))
    app = FastAPI()
    app.include_router(SessionRoutes(sessions=first).identity, prefix="/first")
    app.include_router(SessionRoutes(sessions=second).identity, prefix="/second")
    with TestClient(app) as client:
        assert client.get("/first/api/auth/me").json() == {"session": "first"}
        assert client.get("/second/api/auth/me").json() == {"session": "second"}
        first.return_value = SimpleNamespace(current_user=lambda request: {"session": "renewed"})
        assert client.get("/first/api/auth/me").json() == {"session": "renewed"}
        assert client.get("/second/api/auth/me").json() == {"session": "second"}
    assert first.call_count == second.call_count == 2


@pytest.mark.parametrize("domain", ["profile", "administration"])
def test_included_domain_router_runs_parent_and_account_gates_before_service(domain):
    calls = []
    principal = User(id=71, username="synthetic-owner", role="admin")

    def parent_gate(request: Request):
        calls.append("parent")
        if request.headers.get("x-test-workspace") != "allowed":
            raise HTTPException(403, "workspace denied")

    def user_gate(request: Request):
        calls.append("account")
        if request.headers.get("x-test-account") != "allowed":
            raise HTTPException(401, "account denied")
        return principal

    service = Mock()
    service.get.return_value = {"user_id": 71}
    factory = Mock(return_value=service)
    if domain == "profile":
        router = ProfileRoutes(profile=factory, authenticated_user=user_gate).router
        path = "/api/auth/profile"
        expected_arguments = (principal,)
    else:
        router = AdministrationRoutes(users=factory, require_admin=user_gate).router
        path = "/api/users/71"
        expected_arguments = (71, principal)
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(parent_gate)])
    with TestClient(app) as client:
        assert client.get(path).status_code == 403
        assert calls == ["parent"]
        factory.assert_not_called()
        calls.clear()
        assert client.get(path, headers={"x-test-workspace": "allowed"}).status_code == 401
        assert calls == ["parent", "account"]
        factory.assert_not_called()
        calls.clear()
        response = client.get(
            path, headers={"x-test-workspace": "allowed", "x-test-account": "allowed"}
        )
    assert response.status_code == 200 and response.json() == {"user_id": 71}
    assert calls == ["parent", "account"]
    factory.assert_called_once_with()
    service.get.assert_called_once_with(*expected_arguments)
