"""The inventory diagnoses dispatch obstacles without running business code."""

import importlib.util
from pathlib import Path

from fastapi import FastAPI


def auditor():
    path = Path(__file__).resolve().parents[2] / "scripts/dev/ai_runtime_contract_inventory.py"
    spec = importlib.util.spec_from_file_location("ai_runtime_contract_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inventory


def test_inventory_detects_real_duplicate_and_static_shadowing_without_execution():
    app = FastAPI()

    @app.get("/api/customers/{customer_id}")
    def customer(customer_id: str):
        raise AssertionError("audit must not execute business functions")

    @app.get("/api/customers/export", include_in_schema=False)
    def export():
        raise AssertionError("must not execute")

    app.add_api_route("/api/customers/export", export, methods=["GET"])
    app.add_api_route("/api/health", export, methods=["GET"])
    report = auditor()(app)
    assert report["counts"]["registrations"] == 4
    assert report["counts"]["unique_path_methods"] == 3
    assert report["counts"]["duplicated_path_methods"] == 1
    exports = [row for row in report["operations"] if row["path"].endswith("/export")]
    assert len(exports) == 2
    assert exports[0]["static_path_shadowed_by"] == ["/api/customers/{customer_id}"]
    assert exports[1]["static_path_shadowed_by"] == [
        "/api/customers/{customer_id}",
        "/api/customers/export",
    ]
    assert all(row["schema_status"] == "AMBIGUOUS_OPERATION" for row in exports)
    assert report["business_coverage_percent"] is None


def test_audit_typed_converter_does_not_falsely_shadow_static_name():
    app = FastAPI()
    app.add_api_route("/api/customer/{customer_id:int}", lambda customer_id: {})
    app.add_api_route("/api/customer/export", lambda: {})
    report = auditor()(app)
    assert not report["operations"][1]["static_path_shadowed_by"]
    assert report["counts"]["schema_status_by_unique_operation"] == {"available": 2}


def test_print_dispatch_reaches_authenticated_label_handler_not_file_catchall():
    from fastapi.testclient import TestClient

    from app.fastapi_routes import ai_assistant

    app = FastAPI()
    app.include_router(ai_assistant.router)
    with TestClient(app) as client:
        for endpoint in ("single_label", "pdf_labels"):
            assert client.post(f"/api/print/{endpoint}", json={}).status_code == 401
        assert client.post("/api/print/missing.pdf", json={}).status_code in {400, 404}


def test_settings_dispatch_has_one_canonical_owner(monkeypatch):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from app.fastapi_routes import lan_admin_routes, lan_settings_routes

    calls = []

    def reject(request):
        calls.append(request.method)
        raise HTTPException(status_code=403, detail="canonical-authorizer")

    monkeypatch.setattr(lan_settings_routes, "_authorize", reject)
    app = FastAPI()
    app.include_router(lan_admin_routes.router)
    app.include_router(lan_settings_routes.router)
    with TestClient(app) as client:
        for method in ("GET", "POST", "PUT"):
            response = client.request(
                method, "/api/lan/admin/settings", json={} if method != "GET" else None
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "canonical-authorizer"
    assert calls == ["GET", "POST", "PUT"]
    report = auditor()(app)
    settings = [row for row in report["operations"] if row["path"] == "/api/lan/admin/settings"]
    assert len(settings) == 3
    assert all(
        row["registrations"] == 1 and row["schema_status"] == "available" for row in settings
    )


def test_shipped_registration_profile_has_no_duplicate_or_static_shadowed_api(monkeypatch):
    from app.fastapi_routes import register_all_routes

    monkeypatch.setenv("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "0")
    app = FastAPI()
    register_all_routes(app)
    report = auditor()(app)
    # Opt-in local artifact output; normal CI tests never rewrite evidence files.
    import json
    import os

    output = os.environ.get("XCMAX_API_CONTRACT_REPORT")
    if output:
        report["registration_profile"] = (
            "register_all_routes; legacy compatibility enabled; pytest isolated environment; no lifespan"
        )
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    counts = report["counts"]
    assert counts["unique_path_methods"] > 0
    assert counts["duplicated_path_methods"] == 0, [
        row for row in report["operations"] if row["registrations"] > 1
    ]
    assert counts["static_shadowed_registrations"] == 0, [
        row for row in report["operations"] if row["static_path_shadowed_by"]
    ]
    assert counts["schema_status_by_unique_operation"] == {
        "available": counts["unique_path_methods"]
    }
