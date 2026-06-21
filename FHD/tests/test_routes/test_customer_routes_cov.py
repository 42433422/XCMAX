from __future__ import annotations

"""Branch-coverage ramp for app.fastapi_routes.domains.customer.routes.

Targets 32 missing branches (61.9% → higher) from coverage_new.json.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.customer import routes as cust_routes
from app.fastapi_routes.domains.customer.routes import (
    _agent_node_output,
    _customers_agent_user_id,
    _execute_customers_route_action,
    router,
)

# ---------------------------------------------------------------------------
# TestClient fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = FastAPI()
    # Minimal mocking: patch publish_route_event decorator at router level
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


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
        assert out["success"] is True

    def test_fallback_failed_with_error_message(self):
        run = _make_run("failed", error="oops")
        out = _agent_node_output(run, "no_match")
        assert out.get("message") == "oops"

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
    def _req(self, headers: dict) -> MagicMock:
        req = MagicMock()
        req.headers = headers
        return req

    def test_from_x_user_id_header(self):
        req = self._req({"X-User-Id": "99"})
        uid = _customers_agent_user_id(req, {})
        assert uid == "99"

    def test_from_x_user_id_upper(self):
        req = self._req({"X-User-ID": "88"})
        uid = _customers_agent_user_id(req, {})
        assert uid == "88"

    def test_from_payload_user_id(self):
        req = self._req({})
        uid = _customers_agent_user_id(req, {"user_id": "77"})
        assert uid == "77"

    def test_from_payload_userId(self):
        req = self._req({})
        uid = _customers_agent_user_id(req, {"userId": "66"})
        assert uid == "66"

    def test_fallback_default(self):
        req = self._req({})
        uid = _customers_agent_user_id(req, {})
        assert uid == "customers-route"


# ===========================================================================
# 3. _execute_customers_route_action (lines 139-206)
# ===========================================================================

class TestExecuteCustomersRouteAction:
    def test_create_success(self):
        with patch("app.fastapi_routes.domains.customer.routes._customer_pg_insert", return_value={"id": 1, "name": "A"}):
            result = _execute_customers_route_action("create", {"customer_name": "A"})
        assert result["success"] is True
        assert result["data"]["id"] == 1

    def test_create_no_name(self):
        result = _execute_customers_route_action("create", {})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_update_success(self):
        with patch("app.fastapi_routes.domains.customer.routes._customer_pg_update", return_value={"id": 5}):
            result = _execute_customers_route_action("update", {"id": 5, "name": "B"})
        assert result["success"] is True

    def test_update_no_id(self):
        result = _execute_customers_route_action("update", {"name": "B"})
        assert result["success"] is False
        assert "缺少 id" in result["message"]

    def test_update_no_name(self):
        result = _execute_customers_route_action("update", {"id": 5})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_delete_success(self):
        with patch("app.fastapi_routes.domains.customer.routes._customer_delete_unified"):
            result = _execute_customers_route_action("delete", {"id": 10})
        assert result["success"] is True

    def test_delete_no_id(self):
        result = _execute_customers_route_action("delete", {"id": 0})
        assert result["success"] is False

    def test_batch_delete_success(self):
        with patch("app.fastapi_routes.domains.customer.routes._customer_delete_unified"):
            result = _execute_customers_route_action("batch_delete", {"ids": [1, 2, 3]})
        assert result["success"] is True
        assert result["deleted"] == 3

    def test_batch_delete_empty_ids(self):
        result = _execute_customers_route_action("batch_delete", {"ids": []})
        assert result["success"] is False

    def test_batch_delete_non_list(self):
        result = _execute_customers_route_action("batch_delete", {"ids": "bad"})
        assert result["success"] is False

    def test_batch_delete_invalid_id_skipped(self):
        with patch("app.fastapi_routes.domains.customer.routes._customer_delete_unified"):
            result = _execute_customers_route_action("batch_delete", {"ids": [1, "abc", 2]})
        assert result["deleted"] == 2
        assert "abc" in result["skipped"]

    def test_batch_delete_404_http_exception_skipped(self):
        def _raise_404(cid):
            if cid == 2:
                raise HTTPException(status_code=404)
        with patch("app.fastapi_routes.domains.customer.routes._customer_delete_unified", side_effect=_raise_404):
            result = _execute_customers_route_action("batch_delete", {"ids": [1, 2]})
        assert result["deleted"] == 1
        assert "2" in result["skipped"]

    def test_batch_delete_non_404_raises(self):
        def _raise_500(cid):
            raise HTTPException(status_code=500)
        with patch("app.fastapi_routes.domains.customer.routes._customer_delete_unified", side_effect=_raise_500):
            with pytest.raises(HTTPException):
                _execute_customers_route_action("batch_delete", {"ids": [1]})

    def test_unknown_action(self):
        result = _execute_customers_route_action("unknown", {})
        assert result["success"] is False
        assert "未注册" in result["message"]


# Shorthand for the routes module target path
_ROUTES = "app.fastapi_routes.domains.customer.routes"
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
            with patch(f"{_FACADE}.customers_get", return_value={"success": True, "data": {"id": 2}}):
                r = client.get("/customers/2")
        assert r.status_code == 200


# ===========================================================================
# 5. customers_create (POST /customers) (lines 357-403)
# ===========================================================================

class TestCustomersCreate:
    def test_create_success(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customers_write_raise"):
                with patch(f"{_ROUTES}._customer_body_name_contact", return_value=("TestCo", "p", "111", "addr")):
                    with patch(f"{_ROUTES}._run_customers_agent", return_value={"success": True, "data": {"id": 1}}):
                        with patch(f"{_ROUTES}.publish_simple_event"):
                            r = client.post("/customers", json={"name": "TestCo"})
        assert r.status_code == 200

    def test_create_empty_name_returns_400(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customers_write_raise"):
                with patch(f"{_ROUTES}._customer_body_name_contact", return_value=("", "", "", "")):
                    r = client.post("/customers", json={})
        assert r.status_code == 400

    def test_create_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_create", return_value={"success": True}):
                r = client.post("/customers", json={"name": "TestCo"})
        assert r.status_code == 200


# ===========================================================================
# 6. customers_delete (DELETE /customers/{id}) (lines 444-467)
# ===========================================================================

class TestCustomersDelete:
    def test_delete_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_delete", return_value={"success": True}):
                r = client.delete("/customers/5")
        assert r.status_code == 200

    def test_delete_not_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customers_write_raise"):
                with patch(f"{_ROUTES}._run_customers_agent", return_value={"success": True}):
                    r = client.delete("/customers/5")
        assert r.status_code == 200

    def test_delete_recoverable_error_fallthrough(self, client: TestClient):
        import httpx
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", side_effect=httpx.ConnectError("err")):
            with patch(f"{_ROUTES}._customers_write_raise"):
                with patch(f"{_ROUTES}._run_customers_agent", return_value={"success": True}):
                    r = client.delete("/customers/5")
        assert r.status_code == 200


# ===========================================================================
# 7. customers_update (PUT /customers/{id}) (lines 406-441)
# ===========================================================================

class TestCustomersUpdate:
    def test_update_no_name_400(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=False):
            with patch(f"{_ROUTES}._customers_write_raise"):
                with patch(f"{_ROUTES}._customer_body_name_contact", return_value=("", "", "", "")):
                    r = client.put("/customers/1", json={})
        assert r.status_code == 400

    def test_update_via_service(self, client: TestClient):
        with patch(f"{_FACADE}.is_erp_customers_via_service_enabled", return_value=True):
            with patch(f"{_FACADE}.customers_update", return_value={"success": True}):
                r = client.put("/customers/1", json={"name": "Updated"})
        assert r.status_code == 200


# ===========================================================================
# 8. customers_batch_delete (POST /customers/batch-delete) (lines 470-482)
# ===========================================================================

class TestCustomersBatchDelete:
    def test_batch_delete_empty_ids_raises_400(self, client: TestClient):
        with patch(f"{_ROUTES}._customers_write_raise"):
            r = client.post("/customers/batch-delete", json={"ids": []})
        assert r.status_code == 400

    def test_batch_delete_no_ids_field_raises_400(self, client: TestClient):
        with patch(f"{_ROUTES}._customers_write_raise"):
            r = client.post("/customers/batch-delete", json={})
        assert r.status_code == 400

    def test_batch_delete_success(self, client: TestClient):
        with patch(f"{_ROUTES}._customers_write_raise"):
            with patch(f"{_ROUTES}._run_customers_agent", return_value={"success": True, "deleted": 2}):
                r = client.post("/customers/batch-delete", json={"ids": [1, 2]})
        assert r.status_code == 200


# ===========================================================================
# 9. customers_import (POST /customers/import) (lines 485-502)
# ===========================================================================

class TestCustomersImport:
    def test_import_business_mod_blocked(self, client: TestClient):
        import io
        with patch(f"{_ROUTES}._customers_write_raise"):
            with patch(f"{_ROUTES}._business_mod_json_block", return_value={"success": False, "message": "blocked"}):
                r = client.post("/customers/import", files={"file": ("f.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_import_success(self, client: TestClient):
        import io
        import sys
        import types

        # run_customers_excel_import_bytes is a lazy import that the module guards via __getattr__
        # Inject a fresh fake into sys.modules before the route handler executes
        fake_excel = types.ModuleType("app.application.excel_imports")
        fake_excel.run_customers_excel_import_bytes = lambda _: {"success": True, "created": 5}  # type: ignore[attr-defined]
        with patch(f"{_ROUTES}._customers_write_raise"):
            with patch(f"{_ROUTES}._business_mod_json_block", return_value=None):
                with patch.dict(sys.modules, {"app.application.excel_imports": fake_excel}):
                    r = client.post("/customers/import", files={"file": ("f.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_import_failure_returns_400(self, client: TestClient):
        import io
        import sys
        import types

        fake_excel = types.ModuleType("app.application.excel_imports")
        fake_excel.run_customers_excel_import_bytes = lambda _: {"success": False, "message": "parse error"}  # type: ignore[attr-defined]
        with patch(f"{_ROUTES}._customers_write_raise"):
            with patch(f"{_ROUTES}._business_mod_json_block", return_value=None):
                with patch.dict(sys.modules, {"app.application.excel_imports": fake_excel}):
                    r = client.post("/customers/import", files={"file": ("f.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.status_code == 400


# ===========================================================================
# 10. customers_export_stub (GET /customers/export) (lines 505-511)
# ===========================================================================

class TestCustomersExportStub:
    def test_export_returns_501(self, client: TestClient):
        # /customers/export conflicts with /customers/{customer_id}
        # The route is registered but the path matches customer_id="export"
        # The route itself raises 501 when directly invoked as a function
        from app.fastapi_routes.domains.customer.routes import customers_export_stub
        with pytest.raises(HTTPException) as exc_info:
            customers_export_stub()
        assert exc_info.value.status_code == 501
