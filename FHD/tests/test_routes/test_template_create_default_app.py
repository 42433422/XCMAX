"""Default factory, real sessions, agent execution and SQLite template readback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.release_gate


@pytest.fixture
def template_app(tmp_path, monkeypatch):
    import app.db as database
    import app.db.init_db as init_db
    import app.db.session as db_session
    import app.fastapi_app.factory as factory
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.application.template_app_service import TemplateApplicationService
    from app.config import TestingConfig
    from app.db.base import Base
    from app.db.models.user import Session, User
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore
    from app.infrastructure.tenant_scope import tenant_scope

    for key, value in {
        "XCAGI_DESKTOP_FAST_START": "0",
        "XCAGI_REGISTER_LEGACY_ROUTES": "0",
        "XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "0",
        "XCAGI_DATA_DIR": str(tmp_path),
        "XCAGI_DESKTOP_DATA_DIR": str(tmp_path),
        "FHD_ALLOW_X_USER_ID_HEADER": "0",
        "XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE": "0",
        "MODEL_USAGE_LEDGER_PATH": str(tmp_path / "usage.json"),
        "MODEL_USAGE_WALLET_BACKEND": "audit",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    db_path = tmp_path / "templates.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr(database, "_get_engine", lambda: engine)
    monkeypatch.setattr(db_session, "SessionLocal", sessions)
    monkeypatch.setattr(init_db, "get_db_path", lambda *_args: str(db_path))
    init_db.init_template_tables(str(db_path))
    with sessions.begin() as db:
        for uid, tid in ((7, 11), (8, 22), (9, None)):
            db.add(User(id=uid, username=f"label-user-{uid}", password="unused", tenant_id=tid))
            db.add(
                Session(
                    session_id=f"label-session-{uid}",
                    user_id=uid,
                    expires_at=datetime.now() + timedelta(hours=1),
                    account_kind="enterprise",
                )
            )
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    service = TemplateApplicationService(FileSystemTemplateStore(str(tmp_path)))
    monkeypatch.setattr(
        "app.application.template_app_service.get_template_app_service", lambda: service
    )
    # Core route registration is real. Optional Mod loading and lifespan workers
    # are excluded so this test cannot launch unrelated runtime/background jobs.
    monkeypatch.setattr(
        "app.fastapi_app.mod_startup.bootstrap_mod_extensions_sync", lambda *_args, **_kw: None
    )
    monkeypatch.setattr(
        "app.fastapi_app.mod_startup.schedule_background_mod_load", lambda _app: None
    )
    monkeypatch.setattr(factory, "_app_singleton", None)
    app = factory.create_fastapi_app(TestingConfig, enable_cors=False)
    client = TestClient(app)
    client.cookies.set("csrf_token", "label-test-csrf")
    client.headers["X-CSRF-Token"] = "label-test-csrf"
    try:
        with tenant_scope(None):
            yield client, engine, repo
    finally:
        client.close()
        engine.dispose()


def _label_payload():
    return {
        "name": "验收产品标签",
        "template_type": "标签",
        "category": "label",
        "source": "generated",
        "fields": [
            {
                "id": "editor-field-1",
                "label": "产品名称",
                "value": "",
                "type": "dynamic",
                "position": {"left": 50, "top": 90, "width": 150, "height": 40},
            }
        ],
        "preview_data": {"grid": None, "image_size": {"width": 900, "height": 600}, "image": None},
    }


def _template_count(engine):
    with engine.connect() as db:
        return db.execute(text("SELECT count(*) FROM templates")).scalar_one()


def test_default_factory_registers_only_template_create_mutation(template_app):
    client, _engine, _repo = template_app
    paths = client.app.openapi()["paths"]
    assert "post" in paths["/api/templates/create"]
    assert "post" not in paths.get("/api/templates/update", {})
    assert "delete" not in paths.get("/api/templates/delete", {})


@pytest.mark.parametrize("session_id, expected", [(None, 401), ("label-session-9", 403)])
def test_create_rejects_anonymous_or_missing_tenant_without_writes(
    template_app, session_id, expected
):
    client, engine, _repo = template_app
    headers = {"X-User-ID": "7", "X-Tenant-ID": "11"}
    if session_id:
        headers["X-Session-ID"] = session_id
    response = client.post(
        "/api/templates/create",
        headers=headers,
        json={**_label_payload(), "user_id": 7, "tenant_id": 11},
    )
    assert response.status_code == expected, response.text
    assert _template_count(engine) == 0


def test_label_create_readback_uses_authenticated_owner_and_tenant(template_app, tmp_path):
    from pypdf import PdfReader

    from app.application.label_job_service import LabelJobService
    from app.db.models.product import Product

    client, engine, repo = template_app
    body = {**_label_payload(), "user_id": 8, "userId": 8, "tenant_id": 22}
    headers = {"X-Session-ID": "label-session-7", "X-User-ID": "8", "X-Tenant-ID": "22"}
    response = client.post("/api/templates/create", headers=headers, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True, payload
    run = repo.get(payload["run_id"])
    assert run.user_id == "7"
    assert run.status == "completed"
    assert run.tool_calls[0].permission == "tool.document_template.create"
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        event.event_type for event in run.events
    }
    template_id = payload["template"]["id"]
    with engine.connect() as db:
        stored = db.execute(text("SELECT tenant_id, analyzed_data FROM templates")).one()
        assert stored.tenant_id == 11
        assert json.loads(stored.analyzed_data)["preview_data"] == body["preview_data"]
        assert (
            db.execute(
                text("SELECT count(*) FROM template_usage_log WHERE action='create'")
            ).scalar_one()
            == 1
        )
    rows = client.get("/api/templates", headers=headers).json()["templates"]
    row = next(row for row in rows if row["id"] == template_id)
    detail = client.get(f"/api/templates/{template_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    for result in (payload["template"], row, detail.json()["template"]):
        for key in ("category", "fields", "preview_data"):
            assert result[key] == body[key]
    other_headers = {"X-Session-ID": "label-session-8"}
    assert client.get(f"/api/templates/{template_id}", headers=other_headers).status_code == 404
    assert all(
        row["id"] != template_id
        for row in client.get("/api/templates", headers=other_headers).json()["templates"]
    )
    with engine.begin() as db:
        db.execute(
            Product.__table__.insert().values(id=31, tenant_id=11, name="标签验收产品", is_active=1)
        )
    service = LabelJobService(tmp_path / "label_jobs")
    job = service.generate(
        (11, 7),
        {
            "product_id": 31,
            "template_id": template_id,
            "copies": 1,
            "paper_width_mm": 90,
            "paper_height_mm": 60,
        },
    )
    assert job["status"] == "generated"
    pdf = PdfReader(service.file((11, 7), job["id"]))
    assert len(pdf.pages) == 1
    assert "标签验收产品" in pdf.pages[0].extract_text()
    _, saved_job = service._read((11, 7), job["id"])
    assert saved_job["layout"]["fields"][0]["left"] == 50
    assert saved_job["layout"]["fields"][0]["top"] == 90
