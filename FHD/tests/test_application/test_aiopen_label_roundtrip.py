"""Actual authenticated AI API calls generate and retrieve an owned label PDF."""

from sqlalchemy import text

from app.application.aiopen.api_artifacts import read_api_export
from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call
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
