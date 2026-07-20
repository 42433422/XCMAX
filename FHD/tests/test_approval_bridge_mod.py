from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI
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
    assert "app.application.approval_workspace_app_service" in text


def test_approval_bridge_get_routes_call_application_service(monkeypatch):
    from app.application import approval_workspace_app_service as svc

    monkeypatch.setattr(
        svc, "list_flows", lambda is_active, business_type: {"success": True, "data": []}
    )
    monkeypatch.setattr(
        svc,
        "list_requests",
        lambda approver_id, applicant_id, status, business_type, page, page_size: {
            "success": True,
            "data": [],
        },
    )
    spec = importlib.util.spec_from_file_location(
        "test_xcagi_approval_bridge_blueprints",
        MOD_DIR / "backend" / "blueprints.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    module.register_fastapi_routes(app, "xcagi-approval-bridge")
    client = TestClient(app)

    assert client.get("/api/mod/xcagi-approval-bridge/flows").status_code == 200
    assert client.get("/api/mod/xcagi-approval-bridge/requests").status_code == 200


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
