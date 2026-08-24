from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.template.routes import router


def test_template_domain_upload_is_available_in_current_host(monkeypatch):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "ingested": True,
            "template": {"id": "db:7", "name": kwargs["template_name"]},
        }, 200

    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        fake_ingest,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/templates/upload",
        files={
            "file": (
                "国圣化工.xlsx",
                b"synthetic-workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={
            "template_name": "国圣化工 · 发货单模板",
            "template_scope": "orders",
            "source": "chat_office_docking_ai_advice",
        },
    )

    assert response.status_code == 200
    assert response.json()["ingested"] is True
    assert captured == {
        "file_body": b"synthetic-workbook",
        "filename": "国圣化工.xlsx",
        "template_name": "国圣化工 · 发货单模板",
        "template_scope": "orders",
        "source": "chat_office_docking_ai_advice",
    }


def test_template_domain_upload_does_not_treat_file_type_as_business_scope(monkeypatch):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)
        return {"success": True, "ingested": True}, 201

    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        fake_ingest,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/templates/upload",
        files={"file": ("说明.docx", b"synthetic-document")},
        data={"name": "说明模板", "type": "word"},
    )

    assert response.status_code == 201
    assert captured["template_name"] == "说明模板"
    assert captured["template_scope"] == ""
