from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "xcagi-approval-bridge"


def test_approval_manifest_facade_flag():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-approval-bridge")
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("approval_facade") is True


def test_approval_blueprints_delegate_routes():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-approval-bridge")
    text = (MOD_DIR / "backend" / "blueprints.py").read_text(encoding="utf-8")
    assert "/requests" in text
    assert "/flows" in text
    assert "approval_workspace_app_service" in text
    assert "app.fastapi_routes.approval" not in text


def _load_approval_bridge_blueprints():
    module_name = "_test_xcagi_approval_bridge_blueprints"
    spec = importlib.util.spec_from_file_location(
        module_name,
        MOD_DIR / "backend" / "blueprints.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_approval_bridge_runtime_delegates_list_and_approve(monkeypatch):
    module = _load_approval_bridge_blueprints()
    calls: dict[str, object] = {}

    def fake_list_requests(*args):
        calls["list"] = args
        return {"success": True, "data": [{"id": 17}]}

    def fake_approve(request_id, request, body, x_user_id):
        assert isinstance(request, Request)
        calls["approve"] = (request_id, body, x_user_id)
        return {"success": True, "data": {"id": request_id, "status": "approved"}}

    monkeypatch.setattr(module.svc, "list_requests", fake_list_requests)
    monkeypatch.setattr(module.svc, "approve_request", fake_approve)

    app = FastAPI()
    module.register_fastapi_routes(app, "xcagi-approval-bridge")
    client = TestClient(app)

    listed = client.get(
        "/api/mod/xcagi-approval-bridge/requests",
        params={"approver_id": 2, "page": 1, "page_size": 200},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == [{"id": 17}]
    assert calls["list"] == (2, None, None, None, 1, 200)

    approved = client.post(
        "/api/mod/xcagi-approval-bridge/requests/17/approve",
        headers={"X-User-ID": "2"},
        json={"opinion": "同意"},
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "approved"
    assert calls["approve"] == (17, {"opinion": "同意"}, "2")


def test_list_approval_facade_registry_mod(monkeypatch):
    from app.mod_sdk import approval_compat as ac

    monkeypatch.setattr(ac, "is_approval_via_mod_enabled", lambda: True)
    data = ac.list_approval_facade_registry()
    from tests.mod_sdk_expectations import MOD_FACADE_EXECUTION_PATHS

    assert data.get("execution_path") in MOD_FACADE_EXECUTION_PATHS
    assert data.get("endpoint_count", 0) >= 10


def test_platform_shell_lists_approval_facade():
    from app.mod_sdk.platform_shell import BRIDGE_MOD_HOST_APIS

    prefixes = BRIDGE_MOD_HOST_APIS.get("xcagi-approval-bridge") or []
    assert any("xcagi-approval-bridge" in p for p in prefixes)
