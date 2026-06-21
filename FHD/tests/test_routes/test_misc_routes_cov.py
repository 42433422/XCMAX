from __future__ import annotations

"""Branch-coverage ramp for app.fastapi_routes.domains.misc.routes.

Targets 33 missing branches (43.1% → higher) from coverage_new.json.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.misc import routes as misc_routes
from app.fastapi_routes.domains.misc.routes import (
    _compat_current_db_display_label,
    _memory_v2_agent_output,
    _resolve_user_id_int,
    _test_db_toggle_from_body,
    router,
)

# ---------------------------------------------------------------------------
# TestClient fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# 1. fhd_db_write_token_verify (lines 32-35)
# ===========================================================================

class TestDbWriteTokenVerify:
    def test_no_expected_always_valid(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.configured_db_write_token", return_value=""):
            r = client.post("/fhd/db-write-token/verify", json={"token": "any"})
        assert r.status_code == 200
        assert r.json()["valid"] is True
        assert r.json()["write_token_required"] is False

    def test_correct_token_valid(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.configured_db_write_token", return_value="secret"):
            r = client.post("/fhd/db-write-token/verify", json={"token": "secret"})
        assert r.json()["valid"] is True
        assert r.json()["write_token_required"] is True

    def test_wrong_token_invalid(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.configured_db_write_token", return_value="secret"):
            r = client.post("/fhd/db-write-token/verify", json={"token": "bad"})
        assert r.json()["valid"] is False


# ===========================================================================
# 2. fhd_db_read_token_verify (lines 38-57)
# ===========================================================================

class TestDbReadTokenVerify:
    def test_no_expected_always_valid(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.effective_db_read_token", return_value=""):
            r = client.post("/fhd/db-read-token/verify", json={"token": "any"})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["read_token_required"] is False

    def test_correct_read_token(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.effective_db_read_token", return_value="tok"):
            with patch(
                "app.fastapi_routes.domains.conversation.helpers._touch_chat_db_read_grace",
                return_value=300,
            ):
                r = client.post("/fhd/db-read-token/verify", json={"token": "tok"})
        assert r.json()["valid"] is True

    def test_wrong_read_token(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.effective_db_read_token", return_value="tok"):
            r = client.post("/fhd/db-read-token/verify", json={"token": "wrong"})
        assert r.json()["valid"] is False
        assert r.json()["grace_seconds"] == 0


# ===========================================================================
# 3. _test_db_toggle_from_body (lines 70-92)
# ===========================================================================

class TestTestDbToggleFromBody:
    def test_bool_true(self):
        assert _test_db_toggle_from_body({"enabled": True}) is True

    def test_bool_false(self):
        assert _test_db_toggle_from_body({"enabled": False}) is False

    def test_int_one(self):
        assert _test_db_toggle_from_body({"on": 1}) is True

    def test_int_zero(self):
        assert _test_db_toggle_from_body({"on": 0}) is False

    def test_str_true_values(self):
        for v in ("true", "1", "yes", "on"):
            assert _test_db_toggle_from_body({"enable": v}) is True

    def test_str_false_values(self):
        for v in ("false", "0", "no", "off"):
            assert _test_db_toggle_from_body({"enable": v}) is False

    def test_no_matching_key(self):
        assert _test_db_toggle_from_body({"other": True}) is None

    def test_empty_body(self):
        assert _test_db_toggle_from_body({}) is None

    def test_float_value(self):
        assert _test_db_toggle_from_body({"value": 1.0}) is True


# ===========================================================================
# 4. _compat_current_db_display_label (lines 95-106)
# ===========================================================================

class TestCompatCurrentDbDisplayLabel:
    def test_postgresql_with_db_and_host(self):
        info = {
            "mode": "production",
            "backend": "postgresql",
            "postgresql_summary": {"database_name": "mydb", "host_port": "localhost:5432"},
            "current_db_name": "mydb",
        }
        label = _compat_current_db_display_label(info)
        assert "mydb" in label
        assert "PostgreSQL" in label

    def test_postgresql_only_db_name(self):
        info = {
            "mode": "production",
            "backend": "postgresql",
            "postgresql_summary": {"database_name": "mydb", "host_port": ""},
            "current_db_name": "mydb",
        }
        label = _compat_current_db_display_label(info)
        assert "mydb" in label

    def test_postgresql_no_summary(self):
        info = {
            "mode": "production",
            "backend": "postgresql",
            "postgresql_summary": {},
            "current_db_name": "mydb",
        }
        label = _compat_current_db_display_label(info)
        assert "PostgreSQL" in label

    def test_sqlite_test_mode(self):
        info = {"mode": "test", "backend": "sqlite", "current_db_name": "test.db"}
        label = _compat_current_db_display_label(info)
        assert "测试" in label

    def test_sqlite_production_mode(self):
        info = {"mode": "production", "backend": "sqlite", "current_db_name": "prod.db"}
        label = _compat_current_db_display_label(info)
        assert "真实" in label


# ===========================================================================
# 5. system_test_db_status (lines 109-124)
# ===========================================================================

class TestSystemTestDbStatus:
    def test_status_returns_mode(self, client: TestClient):
        db_info = {"mode": "production", "backend": "sqlite", "current_db_name": "db.sqlite"}
        with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
            r = client.get("/system/test-db/status")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["test_mode"] is False

    def test_status_test_mode(self, client: TestClient):
        db_info = {"mode": "test", "backend": "sqlite", "current_db_name": "test.db"}
        with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
            r = client.get("/system/test-db/status")
        assert r.json()["data"]["test_mode"] is True


# ===========================================================================
# 6. system_test_db_enable (lines 127-152)
# ===========================================================================

class TestSystemTestDbEnable:
    def test_enable_with_explicit_true(self, client: TestClient):
        db_info = {"mode": "test", "backend": "sqlite", "current_db_name": "test.db"}
        with patch("app.fastapi_routes.domains.misc.routes.switch_to_test_mode", return_value={"success": True}):
            with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
                r = client.post("/system/test-db/enable", json={"enabled": True})
        assert r.status_code == 200

    def test_enable_with_false_switches_production(self, client: TestClient):
        db_info = {"mode": "production", "backend": "sqlite", "current_db_name": "prod.db"}
        with patch("app.fastapi_routes.domains.misc.routes.switch_to_production_mode", return_value={"success": True}):
            with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
                r = client.post("/system/test-db/enable", json={"enabled": False})
        assert r.status_code == 200

    def test_enable_with_no_body_uses_resolve_mode(self, client: TestClient):
        db_info = {"mode": "production", "backend": "sqlite", "current_db_name": "prod.db"}
        with patch("app.fastapi_routes.domains.misc.routes.resolve_mode", return_value="production"):
            with patch("app.fastapi_routes.domains.misc.routes.switch_to_test_mode", return_value={"success": True}):
                with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
                    r = client.post("/system/test-db/enable")
        assert r.status_code == 200

    def test_enable_error_returns_400(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.switch_to_test_mode", return_value={"error": "fail", "message": "db error"}):
            with patch("app.fastapi_routes.domains.misc.routes.resolve_mode", return_value="production"):
                r = client.post("/system/test-db/enable", json={"enabled": True})
        assert r.status_code == 400


# ===========================================================================
# 7. system_test_db_disable (lines 155-161)
# ===========================================================================

class TestSystemTestDbDisable:
    def test_disable_switches_production(self, client: TestClient):
        db_info = {"mode": "production", "backend": "sqlite", "current_db_name": "prod.db"}
        with patch("app.fastapi_routes.domains.misc.routes.switch_to_production_mode", return_value={"success": True}):
            with patch("app.fastapi_routes.domains.misc.routes.get_db_status", return_value=db_info):
                r = client.post("/system/test-db/disable")
        assert r.status_code == 200


# ===========================================================================
# 8. _resolve_user_id_int (lines 481-493)
# ===========================================================================

class TestResolveUserIdInt:
    def test_from_header_x_user_id(self):
        req = MagicMock()
        req.headers = {"X-User-Id": "42"}
        assert _resolve_user_id_int(req) == 42

    def test_from_body_user_id(self):
        req = MagicMock()
        req.headers = {}
        assert _resolve_user_id_int(req, {"user_id": "7"}) == 7

    def test_from_body_userId_camel(self):
        req = MagicMock()
        req.headers = {}
        assert _resolve_user_id_int(req, {"userId": "3"}) == 3

    def test_default_when_no_user_id(self):
        req = MagicMock()
        req.headers = {}
        assert _resolve_user_id_int(req) == 1

    def test_invalid_int_falls_back_to_one(self):
        req = MagicMock()
        req.headers = {"X-User-Id": "not-a-number"}
        assert _resolve_user_id_int(req) == 1


# ===========================================================================
# 9. _memory_v2_agent_output (lines 189-207)
# ===========================================================================

class TestMemoryV2AgentOutput:
    def test_output_from_final_output_node_outputs(self):
        run = MagicMock()
        run.final_output = {"node_outputs": {"n1": {"success": True, "data": []}}}
        run.run_id = "r123"
        run.status = "completed"
        run.error = ""
        out = _memory_v2_agent_output(run, "n1")
        assert out.get("success") is True
        assert out.get("run_id") == "r123"

    def test_output_from_steps_when_final_empty(self):
        step = MagicMock()
        step.node_id = "n2"
        step.output = {"success": True}
        run = MagicMock()
        run.final_output = None
        run.steps = [step]
        run.run_id = "r456"
        run.status = "completed"
        run.error = ""
        out = _memory_v2_agent_output(run, "n2")
        assert out.get("success") is True

    def test_default_output_when_no_match(self):
        run = MagicMock()
        run.final_output = None
        run.steps = []
        run.run_id = ""
        run.status = "completed"
        run.error = ""
        out = _memory_v2_agent_output(run, "missing")
        assert "success" in out

    def test_error_message_populated_from_run_error(self):
        run = MagicMock()
        run.final_output = None
        run.steps = []
        run.run_id = ""
        run.status = "failed"
        run.error = "something broke"
        out = _memory_v2_agent_output(run, "n3")
        assert out.get("message") == "something broke"


# ===========================================================================
# 10. Preferences routes
# ===========================================================================

class TestPreferences:
    def test_get_preferences(self, client: TestClient):
        r = client.get("/preferences?user_id=user1")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["data"]["user_id"] == "user1"

    def test_post_preferences(self, client: TestClient):
        r = client.post("/preferences", json={"theme": "dark"})
        assert r.status_code == 200
        assert r.json()["data"].get("theme") == "dark"


# ===========================================================================
# 11. Tools / Tool-categories routes
# ===========================================================================

class TestToolsRoutes:
    def test_compat_tools_list_no_role(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.get_tools_payload", return_value={"tools": []}):
            r = client.get("/tools")
        assert r.status_code == 200

    def test_compat_tools_list_with_role_filter(self, client: TestClient):
        tools = [{"name": "t1", "roles": ["admin"]}, {"name": "t2", "roles": ["user"]}]
        with patch("app.fastapi_routes.domains.misc.routes.get_tools_payload", return_value={"tools": tools}):
            r = client.get("/tools?role=admin")
        assert r.status_code == 200
        data = r.json()
        assert all("admin" in t.get("roles", []) for t in data.get("tools", []))

    def test_tool_categories(self, client: TestClient):
        with patch("app.fastapi_routes.domains.misc.routes.get_tool_categories_payload", return_value={"categories": []}):
            r = client.get("/tool-categories")
        assert r.status_code == 200
