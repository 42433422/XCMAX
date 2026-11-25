"""Live Mod SDK mutations cannot bypass canonical authority or approval."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk import erp_customers_facade as customers
from app.mod_sdk import erp_products_facade as products
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

MOD_ID = "xcagi-erp-domain-bridge"
MOD_DIR = Path(__file__).resolve().parents[2] / "mods" / "bridge" / MOD_ID
CASES = [
    ("POST", "/products/add", {"name": "Resin", "model_number": "R1"}, "create", True),
    ("POST", "/products/update", {"id": 1, "name": "Resin v2"}, "update", True),
    ("POST", "/products/delete", {"id": 1}, "delete", True),
    ("POST", "/products/batch-delete", {"ids": [1, 2]}, "batch_delete", True),
    ("POST", "/products/batch", {"products": [{"name": "Resin"}]}, "batch_create", True),
    ("POST", "/customers", {"name": "Buyer"}, "create", True),
    ("PUT", "/customers/1", {"name": "Buyer v2", "expected_version": 2}, "update", True),
    ("DELETE", "/customers/1", None, "delete", False),
]


@pytest.mark.parametrize("method,path,body,action,global_store", CASES)
def test_mod_sdk_write_uses_real_canonical_admission(
    monkeypatch, trusted_actor, method, path, body, action, global_store
):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    actor = trusted_actor(
        user_id=7,
        role="admin",
        tier="admin" if global_store else "enterprise",
        tenant_id=None if global_store else 7,
        mod_id=MOD_ID,
    )
    denied = trusted_actor(user_id=8, role="no-tools", permissions=[], mod_id=MOD_ID)
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setattr(
        "app.infrastructure.persistence.compat_db.compat_db_base.get_sync_engine",
        lambda: actor.factory.kw["bind"],
    )
    monkeypatch.setattr(products, "is_erp_products_via_service_enabled", lambda: True)
    monkeypatch.setattr(customers, "is_erp_customers_via_service_enabled", lambda: True)
    effects = Mock(side_effect=AssertionError("Denied or pending SDK writes must not execute"))
    monkeypatch.setattr(products, "_service", effects)
    monkeypatch.setattr(customers, "_service", effects)
    monkeypatch.setattr(
        "app.domain.shared_services.tools_workflow_dispatch.execute_registered_workflow_tool",
        effects,
    )
    handlers = import_mod_backend_py(str(MOD_DIR), MOD_ID, "domain_handlers")
    blueprints = import_mod_backend_py(str(MOD_DIR), MOD_ID, "blueprints")
    monkeypatch.setattr(blueprints, "_invoke", handlers.run_domain_handler)
    app = FastAPI()
    blueprints.register_fastapi_routes(app, MOD_ID)
    url = f"/api/mod/{MOD_ID}{path}"
    with (
        tenant_scope(None),
        TestClient(
            app, headers={**actor.headers, "Idempotency-Key": "sdk-command-1", "X-User-Id": "999"}
        ) as client,
    ):
        response = client.request(method, url, json=body)
        replay = client.request(method, url, json=body)
        payload = response.json()
        if global_store:
            assert response.status_code == replay.status_code == 403, response.text
            assert payload["error_code"] == "approval_scope_required"
            assert payload["execution_status"] == "not_started"
            assert not payload.get("run_id")
        else:
            assert response.status_code == replay.status_code == 202, response.text
            assert payload["pending_approval"] is True and payload["success"] is False
            assert replay.json()["run_id"] == payload["run_id"]
            assert replay.json()["approval_request_id"] == payload["approval_request_id"]
            run = repo.get(payload["run_id"])
            assert run.user_id == "7" and not run.tool_calls
            assert run.steps[0].action == action
        client.headers.update({**denied.headers, "Idempotency-Key": "denied-command"})
        assert client.request(method, url, json=body).status_code == 403
        client.headers.pop("X-Session-ID")
        assert client.request(method, url, json=body).status_code == 401
    effects.assert_not_called()


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: products.products_add(None, {"name": "Resin"}),
        lambda: products.products_update(None, {"id": 1, "name": "Resin"}),
        lambda: products.products_delete(None, {"id": 1}),
        lambda: products.products_batch_delete(None, {"ids": [1]}),
        lambda: products.products_batch(None, {"products": [{"name": "Resin"}]}),
        lambda: customers.customers_create(None, {"name": "Buyer"}),
        lambda: customers.customers_update(None, 1, {"name": "Buyer"}),
        lambda: customers.customers_delete(None, 1),
    ],
)
def test_public_sdk_mutation_requires_bound_request(invoke):
    with pytest.raises(HTTPException) as error:
        invoke()
    assert error.value.status_code == 401


def test_private_sqlite_mod_retired_mutations_never_open_another_store(monkeypatch):
    import importlib.util
    import sys
    from types import SimpleNamespace

    backend = MOD_DIR.parents[1] / "industry" / "taiyangniao-pro" / "backend"
    open_store = Mock(side_effect=AssertionError("Retired Mod mutations must not open any store"))
    monkeypatch.setitem(sys.modules, "database", SimpleNamespace(get_database_path=open_store))
    spec = importlib.util.spec_from_file_location(
        "retired_mod_mutations", backend / "blueprints.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    module.register_fastapi_routes(app, "taiyangniao-pro")
    with TestClient(app) as client:
        for prefix in ("/api/mod/taiyangniao-pro", "/api/mods/taiyangniao-pro"):
            for method, path in (
                ("POST", "/products/add"),
                ("POST", "/products/update"),
                ("POST", "/products/delete"),
                ("POST", "/products/batch-delete"),
                ("POST", "/products/batch"),
                ("POST", "/customers"),
                ("PUT", "/customers/1"),
                ("DELETE", "/customers/1"),
                ("POST", "/customers/batch-delete"),
                ("POST", "/customers/import"),
            ):
                response = client.request(method, prefix + path, json={"id": 1})
                assert response.status_code == 410, response.text
                assert response.json()["error_code"] == "mod_capability_unavailable"
                assert response.json()["execution_status"] == "not_started"
    open_store.assert_not_called()
