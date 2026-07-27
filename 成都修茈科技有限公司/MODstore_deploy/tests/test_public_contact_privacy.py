"""Public contact privacy-consent contract."""

from __future__ import annotations

import json


def _contact_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from modstore_server import market_auth_api as ma
    from modstore_server import models

    db_path = tmp_path / "public_contact.sqlite"
    monkeypatch.setenv("MODSTORE_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = FastAPI()
    app.include_router(ma.router, prefix="/api")
    return TestClient(app), ma


def _contact_payload(**overrides):
    payload = {
        "name": "张三",
        "email": "lead-privacy@example.com",
        "phone": "13800000000",
        "company": "成都路演客户有限公司",
        "message": "咨询获客工单闭环",
        "source": "offline_event",
        "campaign": "brand_acquisition_2026",
        "medium": "qr",
        "content": "event_offline",
    }
    payload.update(overrides)
    return payload


def test_public_contact_requires_privacy_agreement(tmp_path, monkeypatch):
    client, ma = _contact_client(tmp_path, monkeypatch)
    monkeypatch.setattr(ma, "_notify_cs_intake_webhook", lambda _payload: None)

    res = client.post("/api/public/contact", json=_contact_payload())

    assert res.status_code == 400
    assert "隐私政策" in res.json()["detail"]


def test_public_contact_records_privacy_metadata(tmp_path, monkeypatch):
    from modstore_server.models import LandingContactSubmission, get_session_factory

    client, ma = _contact_client(tmp_path, monkeypatch)
    sent_payloads = []
    monkeypatch.setattr(ma, "_notify_cs_intake_webhook", sent_payloads.append)

    res = client.post(
        "/api/public/contact",
        json=_contact_payload(
            privacy_agreed=True,
            privacy_version="2026-06-20",
            privacy_url="/privacy.html",
        ),
    )

    assert res.status_code == 200, res.text
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(LandingContactSubmission)
            .filter(LandingContactSubmission.email == "lead-privacy@example.com")
            .order_by(LandingContactSubmission.id.desc())
            .first()
        )
        assert row is not None
        meta = json.loads(row.meta_json)
    assert meta["privacy_agreed"] is True
    assert meta["privacy_version"] == "2026-06-20"
    assert meta["privacy_url"] == "/privacy.html"
    assert meta["privacy_agreed_at"]
    assert meta["campaign"] == "brand_acquisition_2026"
    assert sent_payloads
    assert sent_payloads[0]["privacy_agreed"] is True
    assert sent_payloads[0]["privacy_version"] == "2026-06-20"
    assert sent_payloads[0]["privacy_url"] == "/privacy.html"
