from __future__ import annotations

"""Branch-coverage ramp for app.fastapi_routes.domains.customer.routes.

Targets 32 missing branches (61.9% → higher) from coverage_new.json.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.customer import routes as cust_routes
from app.fastapi_routes.domains.customer.customer_routes import (
    _agent_node_output,
    _customers_agent_user_id,
    router,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

# ---------------------------------------------------------------------------
# TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(request, monkeypatch):
    actor = None
    if any(action in request.node.name for action in ("create", "update", "delete")):
        actor = request.getfixturevalue("trusted_actor")(tenant_id=7, role="admin")
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    app = FastAPI()
    # Minimal mocking: patch publish_route_event decorator at router level
    app.include_router(router)
    return TestClient(app, headers=actor.headers if actor else {}, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper stubs
# ---------------------------------------------------------------------------


def _make_run(status: str = "completed", run_id: str = "r1", error: str = "") -> MagicMock:
    run = MagicMock()
    run.status = status
    run.run_id = run_id
    run.error = error
    run.final_output = None
    run.steps = []
    return run


# ===========================================================================
# 1. _agent_node_output (lines 42-60)
# ===========================================================================


class TestAgentNodeOutput:
    def test_from_final_output(self):
        run = _make_run()
        run.final_output = {"node_outputs": {"n1": {"success": True}}}
        out = _agent_node_output(run, "n1")
        assert out["success"] is True
        assert out["run_id"] == "r1"

    def test_from_steps(self):
        step = MagicMock()
        step.node_id = "n2"
        step.output = {"success": True, "items": []}
        run = _make_run()
        run.steps = [step]
        out = _agent_node_output(run, "n2")
        assert out["success"] is True

    def test_fallback_completed_status(self):
        run = _make_run("completed")
        out = _agent_node_output(run, "no_match")
        assert out["success"] is False
        assert out["error_code"] == "execution_receipt_missing"

    def test_fallback_failed_with_error_message(self):
        run = _make_run("failed", error="oops")
        out = _agent_node_output(run, "no_match")
        assert out["success"] is False
        assert out["error_code"] == "execution_receipt_missing"

    def test_no_run_id(self):
        run = _make_run(run_id="")
        out = _agent_node_output(run, "n3")
        assert "run_id" not in out or out["run_id"] == ""

    def test_agent_status_included(self):
        run = _make_run("completed")
        out = _agent_node_output(run, "x")
        assert out.get("agent_status") == "completed"


# ===========================================================================
# 2. _customers_agent_user_id (lines 63-70)
# ===========================================================================


class TestCustomersAgentUserId:
    @pytest.mark.parametrize(
        "headers,payload",
        [
            ({"X-User-Id": "99"}, {}),
            ({"X-User-ID": "88"}, {}),
            ({}, {"user_id": "77"}),
            ({}, {"userId": "66"}),
            ({}, {}),
        ],
    )
    def test_untrusted_identity_without_session_is_rejected(self, headers, payload):
        from starlette.requests import Request

        request = Request(
            {
                "type": "http",
                "headers": [
                    (key.lower().encode(), value.encode()) for key, value in headers.items()
                ],
            }
        )
        with pytest.raises(HTTPException) as denied:
            _customers_agent_user_id(request, payload)
        assert denied.value.status_code == 401

    def test_authenticated_identity_ignores_body_spoof(self, trusted_actor):
        actor = trusted_actor(user_id=7)
        assert _customers_agent_user_id(actor.request, {"user_id": "99"}) == "7"


# ===========================================================================
# 3. _execute_customers_route_action (lines 139-206)
# ===========================================================================


# Shorthand for the routes module target path
_ROUTES = "app.fastapi_routes.domains.customer.customer_routes"
# Lazy-import source: erp_customers_facade is imported inside functions
_FACADE = "app.mod_sdk.erp_customers_facade"


# ===========================================================================
# 4. customers_get (GET /customers/{id}) (lines 338-354)
# ===========================================================================


class TestCustomersGetOne:
    def test_get_not_found_raises_404(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customer_find_by_id", return_value=None):
                r = client.get("/customers/999")
        assert r.status_code == 404

    def test_get_found(self, client: TestClient):
        row = {"id": 1, "name": "A"}
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customer_find_by_id", return_value=row):
                with patch(f"{_ROUTES}._customer_row_for_api", return_value=row):
                    r = client.get("/customers/1")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == 1

    def test_get_via_service_enabled(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(
                f"{_FACADE}.customers_get", return_value={"success": True, "data": {"id": 2}}
            ):
                r = client.get("/customers/2")
        assert r.status_code == 200


# ===========================================================================
# 5. customers_create (POST /customers) (lines 357-403)
# ===========================================================================


class TestCustomersCreate:
    def test_create_success(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(
                f"{_ROUTES}._customer_body_name_contact",
                return_value=("TestCo", "p", "111", "addr"),
            ):
                with patch(
                    f"{_ROUTES}._run_customers_agent",
                    return_value=({"success": True, "data": {"id": 1}}, 200),
                ):
                    with patch(f"{_ROUTES}.publish_simple_event"):
                        r = client.post("/customers", json={"name": "TestCo"})
        assert r.status_code == 200

    def test_create_empty_name_returns_400(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customer_body_name_contact", return_value=("", "", "", "")):
                r = client.post("/customers", json={})
        assert r.status_code == 400

    def test_create_service_flag_cannot_bypass_canonical_auth(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_create") as bypass:
                r = client.post("/customers", json={"unit_name": "TestCo"})
        assert r.status_code == 401
        bypass.assert_not_called()


# ===========================================================================
# 6. customers_delete (DELETE /customers/{id}) (lines 444-467)
# ===========================================================================


class TestCustomersDelete:
    def test_delete_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_delete") as bypass:
                r = client.delete("/customers/5")
        assert r.status_code == 400
        assert r.json()["error_code"] == "task_identity_required"
        bypass.assert_not_called()

    def test_delete_not_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._run_customers_agent", return_value=({"success": True}, 200)):
                r = client.delete("/customers/5")
        assert r.status_code == 200

    def test_delete_recoverable_error_fallthrough(self, client: TestClient):
        import httpx

        with patch(
            f"{_FACADE}.is_erp_customers_via_service_enabled", side_effect=httpx.ConnectError("err")
        ):
            with patch(f"{_ROUTES}._run_customers_agent", return_value=({"success": True}, 200)):
                r = client.delete("/customers/5")
        assert r.status_code == 200


# ===========================================================================
# 7. customers_update (PUT /customers/{id}) (lines 406-441)
# ===========================================================================


class TestCustomersUpdate:
    def test_update_no_name_400(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customer_body_name_contact", return_value=("", "", "", "")):
                r = client.put("/customers/1", json={})
        assert r.status_code == 400

    def test_update_service_flag_cannot_bypass_canonical_auth(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_update") as bypass:
                r = client.put("/customers/1", json={"unit_name": "Updated"})
        assert r.status_code == 401
        bypass.assert_not_called()


# ===========================================================================
# 8. customers_batch_delete (POST /customers/batch-delete) (lines 470-482)
# ===========================================================================


class TestCustomersBatchDelete:
    def test_batch_delete_empty_ids_raises_400(self, client: TestClient):
        r = client.post("/customers/batch-delete", json={"ids": []})
        assert r.status_code == 400

    def test_batch_delete_no_ids_field_raises_400(self, client: TestClient):
        r = client.post("/customers/batch-delete", json={})
        assert r.status_code == 400

    def test_batch_delete_success(self, client: TestClient):
        with patch(
            f"{_ROUTES}._run_customers_agent", return_value=({"success": True, "deleted": 2}, 200)
        ):
            r = client.post("/customers/batch-delete", json={"ids": [1, 2]})
        assert r.status_code == 200


# ===========================================================================
# 9. customers_import (POST /customers/import) (lines 485-502)
# ===========================================================================


class TestCustomersImport:
    @pytest.mark.parametrize("suffix", ["", "/"])
    def test_import_requires_real_session_before_staging_or_service(self, client, suffix):
        with patch(
            "app.application.customer_app_service.CustomerApplicationService.import_from_excel"
        ) as execute:
            response = client.post(
                f"/customers/import{suffix}",
                files={"file": ("customers.xlsx", b"original upload")},
                headers={"X-User-Id": "1", "Idempotency-Key": "customer-import"},
            )
        assert response.status_code == 401
        execute.assert_not_called()


# ===========================================================================
# 10. customers_export_stub (GET /customers/export) (lines 505-511)
# ===========================================================================


class TestCustomersExportStub:
    @pytest.mark.parametrize("suffix", ["", "/"])
    def test_export_returns_501(self, client: TestClient, suffix: str):
        response = client.get(f"/customers/export{suffix}")
        assert response.status_code == 501
        assert "/customers 客户页" in response.json()["detail"]
