"""Actual authenticated AI API calls generate and retrieve an owned label PDF."""

from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.application.aiopen.api_artifacts import read_api_export
from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call
from app.db.models.user import Session
from app.fastapi_routes import ai_assistant, print_routes
from tests.test_application.test_aiopen_api_execution import application as application
from tests.test_application.test_aiopen_api_execution import caller
from tests.test_application.test_aiopen_api_execution import host as host
from tests.test_application.test_label_jobs import PAYLOAD
from tests.test_application.test_label_jobs import env as env


def test_ai_generates_owned_label_preview_and_cannot_read_it_as_another_account(
    env, application, monkeypatch, tmp_path
):
    app, _ = application
    app.include_router(print_routes.router)
    app.include_router(ai_assistant.router)
    monkeypatch.setitem(AIOPEN_STATE["whitelist"], "/api/print", True)
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path / "ai-artifacts")
    )
    with env.engine.begin() as db:
        db.execute(text("UPDATE products SET tenant_id=7 WHERE tenant_id=11"))
        db.execute(text("UPDATE templates SET tenant_id=7 WHERE tenant_id=11"))
    with caller({"X-Session-ID": "login-3"}):
        generated = _tool_api_call(
            app, {"path": "/api/print/pdf_labels", "method": "POST", "body": PAYLOAD}
        )
        assert generated["success"], generated
        receipt = generated["data"]
        assert receipt["requires_confirmation"] and receipt["job"]["status"] == "generated"
        preview = _tool_api_call(app, {"path": receipt["preview_url"]})
        assert preview["success"], preview
        assert (
            preview["artifacts"][0]["size"]
            == env.service.file((7, 3), receipt["job"]["id"]).stat().st_size
        )
        content, _ = read_api_export(preview["artifacts"][0]["artifact_id"])
        assert content == env.service.file((7, 3), receipt["job"]["id"]).read_bytes()
        assert preview["execution_scope"]["owner_id"] == "3"
    with caller({"X-Session-ID": "login-5"}):
        denied = _tool_api_call(app, {"path": receipt["preview_url"]})
        assert not denied["success"]
    assert env.service.get((7, 3), receipt["job"]["id"])["status"] == "generated"


def test_direct_label_routes_recheck_mod_entitlement_before_every_operation(
    env, application, host, monkeypatch
):
    from app.fastapi_app.middleware_extra import register_extra_middleware

    app, _ = application
    register_extra_middleware(app)
    app.include_router(print_routes.router)
    app.include_router(ai_assistant.router)
    with env.engine.begin() as db:
        db.execute(text("UPDATE products SET tenant_id=7 WHERE tenant_id=11"))
        db.execute(text("UPDATE templates SET tenant_id=7 WHERE tenant_id=11"))
    monkeypatch.setattr(
        "app.application.facades.print_facade.printer_service.get_label_printer", lambda: "Fixture"
    )
    dispatch = Mock(return_value={"submission_state": "submitted"})
    monkeypatch.setattr("app.fastapi_routes.label_jobs.run_print_agent", dispatch)
    with TestClient(app) as client:
        client.headers.update(
            {
                "X-Session-ID": "login-3",
                "X-XCAGI-Active-Mod-Id": "mod-a",
                "X-CSRF-Token": "label-csrf",
            }
        )
        client.cookies.set("csrf_token", "label-csrf")
        generated = client.post("/api/print/pdf_labels", json=PAYLOAD)
        assert generated.status_code == 200, generated.text
        receipt = generated.json()
        base = f"/api/print/label-jobs/{receipt['job']['id']}"
        assert client.get(base).status_code == 200
        assert client.get(receipt["preview_url"]).status_code == 200
        confirmation = client.post(receipt["confirmation_url"])
        assert confirmation.status_code == 200
        manifest = env.service._directory((7, 3), receipt["job"]["id"]) / "job.json"
        before_revoke = manifest.read_bytes()
        with host.begin() as db:
            db.get(Session, 3).entitled_mod_ids_json = "[]"
        for path in (base, receipt["preview_url"], "/api/print/label-jobs/products"):
            assert client.get(path).status_code == 403
        for path, payload in (
            (receipt["confirmation_url"], {}),
            (receipt["submit_url"], {"confirm_token": confirmation.json()["confirm_token"]}),
            ("/api/print/pdf_labels", PAYLOAD),
            ("/api/print/single_label", PAYLOAD),
            ("/api/print/label-jobs", PAYLOAD),
        ):
            assert client.post(path, json=payload).status_code == 403
        assert manifest.read_bytes() == before_revoke
        dispatch.assert_not_called()
        with host.begin() as db:
            db.get(Session, 3).entitled_mod_ids_json = '["mod-a"]'
        assert client.get(base).json()["job"]["status"] == "generated"
        assert len(list(env.tmp.rglob("labels.pdf"))) == 1
