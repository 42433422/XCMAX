"""Behavioral tests for app.fastapi_routes.desktop_automation route handlers.

All external dependencies (the desktop-automation service singleton, the lazily
imported driver classes, and the lazily imported vision LLM) are mocked so the
suite is deterministic, offline and fast. Covers success paths plus the
error/branch arms (404 profile, vision-call enabled vs disabled, vision LLM
recoverable-error fallback).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import desktop_automation as mod

MOD = "app.fastapi_routes.desktop_automation"


@pytest.fixture
def svc() -> MagicMock:
    """A mock DesktopAutomationService."""
    return MagicMock()


@pytest.fixture
def client(svc: MagicMock) -> TestClient:
    """TestClient whose get_desktop_automation_service returns the mock svc."""
    app = FastAPI()
    app.include_router(mod.router)
    with patch(f"{MOD}.get_desktop_automation_service", return_value=svc):
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /status  (lines 44-45,47 + driver availability)
# ---------------------------------------------------------------------------


class TestAutomationStatus:
    def test_status_reports_profiles_and_driver_availability(
        self, client: TestClient, svc: MagicMock
    ):
        svc.list_profiles.return_value = [{"app_id": "a"}, {"app_id": "b"}]
        with (
            patch("app.desktop_automation.drivers.WindowsDriver") as win,
            patch("app.desktop_automation.drivers.MacDriver") as mac,
            patch("app.desktop_automation.drivers.MCPDriver") as mcp,
        ):
            win.return_value.is_available.return_value = True
            mac.return_value.is_available.return_value = False
            mcp.return_value.is_available.return_value = True
            r = client.get("/api/desktop/automation/status")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["profiles"] == 2
        drivers = body["data"]["drivers"]
        assert drivers["windows"] is True
        assert drivers["mac"] is False
        assert drivers["mcp_wechat"] is True
        # MCPDriver constructed with the wechat_cv element profile id
        mcp.assert_called_once_with("wechat_cv")


# ---------------------------------------------------------------------------
# GET /profiles  (lines 62-63)
# ---------------------------------------------------------------------------


class TestListProfiles:
    def test_returns_service_profiles(self, client: TestClient, svc: MagicMock):
        svc.list_profiles.return_value = [{"app_id": "wechat"}]
        r = client.get("/api/desktop/automation/profiles")
        assert r.status_code == 200
        assert r.json() == {"success": True, "data": {"profiles": [{"app_id": "wechat"}]}}

    def test_empty_profiles(self, client: TestClient, svc: MagicMock):
        svc.list_profiles.return_value = []
        r = client.get("/api/desktop/automation/profiles")
        assert r.json()["data"]["profiles"] == []


# ---------------------------------------------------------------------------
# GET /profiles/{app_id}  (lines 68-72, both branches)
# ---------------------------------------------------------------------------


class TestGetProfile:
    def test_found(self, client: TestClient, svc: MagicMock):
        svc.get_profile.return_value = {"app_id": "wechat", "elements": []}
        r = client.get("/api/desktop/automation/profiles/wechat")
        assert r.status_code == 200
        assert r.json() == {"success": True, "data": {"app_id": "wechat", "elements": []}}
        svc.get_profile.assert_called_once_with("wechat")

    def test_not_found_raises_404(self, client: TestClient, svc: MagicMock):
        svc.get_profile.return_value = None
        r = client.get("/api/desktop/automation/profiles/missing")
        assert r.status_code == 404
        assert r.json()["detail"] == "profile not found"


# ---------------------------------------------------------------------------
# POST /profiles  (lines 77-78)
# ---------------------------------------------------------------------------


class TestRegisterProfile:
    def test_registers_profile(self, client: TestClient, svc: MagicMock):
        svc.register_profile.return_value = {"success": True, "app_id": "x"}
        r = client.post(
            "/api/desktop/automation/profiles",
            json={"profile": {"app_id": "x", "elements": [1, 2]}},
        )
        assert r.status_code == 200
        assert r.json() == {"success": True, "data": {"success": True, "app_id": "x"}}
        svc.register_profile.assert_called_once_with({"app_id": "x", "elements": [1, 2]})

    def test_unavailable_backend_passthrough(self, client: TestClient, svc: MagicMock):
        svc.register_profile.return_value = {"success": False, "error": "unavailable"}
        r = client.post("/api/desktop/automation/profiles", json={"profile": {}})
        # Route always wraps success=True; inner payload carries the failure.
        assert r.json()["success"] is True
        assert r.json()["data"]["success"] is False


# ---------------------------------------------------------------------------
# POST /workflow/run  (lines 83-85)
# ---------------------------------------------------------------------------


class TestRunWorkflow:
    def test_success_passthrough(self, client: TestClient, svc: MagicMock):
        svc.run_workflow.return_value = {"success": True, "steps": 3}
        r = client.post(
            "/api/desktop/automation/workflow/run",
            json={
                "app_id": "wechat",
                "workflow": "open_and_send",
                "params": {"k": "v"},
                "driver": "mac",
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["data"]["steps"] == 3
        svc.run_workflow.assert_called_once_with(
            "wechat", "open_and_send", {"k": "v"}, driver="mac"
        )

    def test_failure_reflected_in_top_level_success(self, client: TestClient, svc: MagicMock):
        svc.run_workflow.return_value = {"success": False, "error": "boom"}
        r = client.post(
            "/api/desktop/automation/workflow/run",
            json={"app_id": "a", "workflow": "w"},
        )
        assert r.json()["success"] is False
        assert r.json()["data"]["error"] == "boom"

    def test_missing_success_key_defaults_false(self, client: TestClient, svc: MagicMock):
        svc.run_workflow.return_value = {"note": "no success key"}
        r = client.post(
            "/api/desktop/automation/workflow/run",
            json={"app_id": "a", "workflow": "w"},
        )
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# POST /send  (lines 90-91,96)
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_maps_body_into_run_workflow_params(self, client: TestClient, svc: MagicMock):
        svc.run_workflow.return_value = {"success": True}
        r = client.post(
            "/api/desktop/automation/send",
            json={
                "app_id": "wechat",
                "contact_name": "张三",
                "message": "hi",
                "workflow": "open_and_send",
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        svc.run_workflow.assert_called_once_with(
            "wechat",
            "open_and_send",
            {"contact_name": "张三", "message": "hi"},
        )

    def test_uses_default_app_and_workflow(self, client: TestClient, svc: MagicMock):
        svc.run_workflow.return_value = {"success": False}
        r = client.post(
            "/api/desktop/automation/send",
            json={"contact_name": "李四", "message": "yo"},
        )
        assert r.json()["success"] is False
        # defaults: app_id="wechat", workflow="open_and_send"
        called_args = svc.run_workflow.call_args
        assert called_args.args[0] == "wechat"
        assert called_args.args[1] == "open_and_send"
        assert called_args.args[2] == {"contact_name": "李四", "message": "yo"}


# ---------------------------------------------------------------------------
# GET /find-element  (lines 101-103)
# ---------------------------------------------------------------------------


class TestFindElement:
    def test_success(self, client: TestClient, svc: MagicMock):
        svc.find_element.return_value = {"success": True, "bbox": [1, 2, 3, 4]}
        r = client.get(
            "/api/desktop/automation/find-element",
            params={"app_id": "wechat", "element_id": "send_btn"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["data"]["bbox"] == [1, 2, 3, 4]
        svc.find_element.assert_called_once_with("wechat", "send_btn")

    def test_not_found_failure(self, client: TestClient, svc: MagicMock):
        svc.find_element.return_value = {"success": False, "error": "no element"}
        r = client.get(
            "/api/desktop/automation/find-element",
            params={"app_id": "wechat", "element_id": "ghost"},
        )
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# POST /bootstrap  (lines 108-110,112-114,116,128-131,133,135-136)
# ---------------------------------------------------------------------------


class TestBootstrapApp:
    def test_without_vision_passes_none_callback(self, client: TestClient, svc: MagicMock):
        svc.bootstrap_app = AsyncMock(return_value={"success": True, "elements": 5})
        r = client.post(
            "/api/desktop/automation/bootstrap",
            json={"app_id": "wechat", "use_vision_api": False},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["data"]["elements"] == 5
        # vision_call must be None when use_vision_api is False
        _, kwargs = svc.bootstrap_app.call_args
        assert kwargs["vision_call"] is None

    def test_with_vision_builds_callable_and_invokes_llm(self, client: TestClient, svc: MagicMock):
        captured = {}

        async def fake_bootstrap(app_id, *, vision_call=None):
            # exercise the inner _vision closure end-to-end
            captured["app_id"] = app_id
            captured["result"] = await vision_call("describe this", "BASE64DATA")
            return {"success": True}

        svc.bootstrap_app = fake_bootstrap
        with patch(
            "app.mod_sdk.mod_employee_llm.mod_employee_complete",
            new=AsyncMock(return_value='{"elements": []}'),
        ) as mock_complete:
            r = client.post(
                "/api/desktop/automation/bootstrap",
                json={"app_id": "wechat", "use_vision_api": True},
            )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert captured["app_id"] == "wechat"
        assert captured["result"] == '{"elements": []}'
        # the prompt + base64 image were threaded into the LLM messages
        mock_complete.assert_awaited_once()
        sent_messages = mock_complete.await_args.args[0]
        content = sent_messages[0]["content"]
        assert content[0] == {"type": "text", "text": "describe this"}
        assert content[1]["image_url"]["url"] == "data:image/png;base64,BASE64DATA"
        assert mock_complete.await_args.kwargs == {"max_tokens": 2048, "temperature": 0.1}

    def test_vision_recoverable_error_returns_empty_json(self, client: TestClient, svc: MagicMock):
        captured = {}

        async def fake_bootstrap(app_id, *, vision_call=None):
            captured["result"] = await vision_call("prompt", "IMG")
            return {"success": False, "error": "no elements detected"}

        svc.bootstrap_app = fake_bootstrap
        # RuntimeError is part of RECOVERABLE_ERRORS -> caught -> returns "{}"
        with patch(
            "app.mod_sdk.mod_employee_llm.mod_employee_complete",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ):
            r = client.post(
                "/api/desktop/automation/bootstrap",
                json={"app_id": "wechat", "use_vision_api": True},
            )
        assert r.status_code == 200
        assert captured["result"] == "{}"
        assert r.json()["success"] is False
        assert r.json()["data"]["error"] == "no elements detected"


# ---------------------------------------------------------------------------
# POST /yolo/export  (lines 141-142)
# ---------------------------------------------------------------------------


class TestExportYolo:
    def test_export(self, client: TestClient, svc: MagicMock):
        svc.export_yolo.return_value = {"dataset": "/tmp/yolo", "images": 0}
        r = client.post(
            "/api/desktop/automation/yolo/export",
            params={"app_id": "wechat"},
        )
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "data": {"dataset": "/tmp/yolo", "images": 0},
        }
        svc.export_yolo.assert_called_once_with("wechat")
