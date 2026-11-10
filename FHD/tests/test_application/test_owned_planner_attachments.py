"""Owned attachment boundary with real sessions, database rows and pinned file IO."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.application.agent_orchestrator.attachment_inputs import resolve_attachment_inputs
from app.db.models.elt import EltUpload
from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
from app.infrastructure.auth.agent_principal import require_agent_principal
from app.infrastructure.tenant_scope import tenant_scope
from evals.run_agent_eval import _authenticated_route_fixture


@pytest.fixture
def owned(monkeypatch, tmp_path):
    from app.utils.path_io import path_utils

    monkeypatch.setattr(path_utils, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.application.elt.service_uploads.get_app_data_dir", lambda: str(tmp_path)
    )
    client = SimpleNamespace(headers={})
    with _authenticated_route_fixture(client, role_name="admin"):
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        context = authenticated_runtime_context(
            {"attachment_upload_ids": ["owned-file"]}, principal
        )
        root = tmp_path / "etl" / "uploads" / principal.tenant_id / principal.user_id
        root.mkdir(parents=True)
        file = root / "owned-file.csv"
        raw = b"product,price\npaint,120\n"
        file.write_bytes(raw)
        from app.db.session import get_db

        with tenant_scope(int(principal.tenant_id)), get_db() as db:
            db.add(
                EltUpload(
                    id="owned-file",
                    tenant_id=int(principal.tenant_id),
                    owner_user_id=int(principal.user_id),
                    file_name="price.csv",
                    suffix=".csv",
                    storage_path=str(file),
                    size_bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        yield context, file


def test_owned_input_is_readable_without_path_or_implicit_ingestion(owned):
    context, _ = owned
    artifact = resolve_attachment_inputs(context)[0]
    assert "paint" in artifact["preview"]["text"]
    assert artifact["uri"] == ""
    assert artifact["metadata"]["skip_dataset_ingest"] is True
    assert artifact["metadata"]["upload_id"] == "owned-file"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", 99),
        ("owner_user_id", 99),
        ("expires_at", datetime(2000, 1, 1)),
        ("sha256", "bad"),
        ("storage_path", "/etc/passwd"),
    ],
)
def test_rejects_changed_ownership_expiry_digest_and_path(owned, field, value):
    context, _ = owned
    from app.db.session import get_db

    with tenant_scope(int(context["tenant_id"])), get_db() as db:
        row = db.query(EltUpload).filter(EltUpload.id == "owned-file").one()
        setattr(row, field, value)
    with pytest.raises((ValueError, RuntimeError)):
        resolve_attachment_inputs(context)


def test_rejects_expired_session_and_byte_tampering(owned):
    context, file = owned
    file.write_bytes(b"attacker")
    with pytest.raises(ValueError, match="校验"):
        resolve_attachment_inputs(context)
    context["_actor_authorization"]["proof"] = "forged"
    with pytest.raises(ValueError, match="授权"):
        resolve_attachment_inputs(context)


def test_legacy_paths_never_become_owned_artifacts():
    assert (
        resolve_attachment_inputs(
            {
                "multimodal_attachments": [{"file_path": "/etc/passwd"}],
                "artifacts": [{"metadata": {"trusted": True}}],
            }
        )
        == []
    )


def test_registered_upload_round_trip_and_missing_tenant(owned):
    import io

    from app.application.elt.service_uploads import register_chat_upload

    context, _ = owned
    user = SimpleNamespace(id=int(context["user_id"]), tenant_id=int(context["tenant_id"]))
    receipt = register_chat_upload(
        user=user,
        filename="second.csv",
        content_type="text/csv",
        stream=io.BytesIO(b"item,count\npencil,8\n"),
    )
    artifact = resolve_attachment_inputs(
        {**context, "attachment_upload_ids": [receipt["upload_id"]]}
    )[0]
    assert "pencil" in artifact["preview"]["text"]
    assert artifact["metadata"]["sha256"] == receipt["sha256"]
    user.tenant_id = None
    from app.application.elt.errors import EltError

    with pytest.raises(EltError, match="租户"):
        register_chat_upload(
            user=user, filename="second.csv", content_type="text/csv", stream=io.BytesIO(b"x,y")
        )


def test_expired_login_cannot_resolve_even_owned_upload(owned):
    context, _ = owned
    from app.db import HostSessionLocal
    from app.db.models.user import Session

    with HostSessionLocal.begin() as db:
        row = db.get(Session, context["_actor_authorization"]["session_row_id"])
        row.expires_at = datetime(2000, 1, 1)
    with pytest.raises(ValueError, match="授权"):
        resolve_attachment_inputs(context)


def test_workbook_preview_preserves_zero_false_and_declares_partial_coverage():
    import io

    from openpyxl import Workbook

    from app.application.agent_orchestrator.attachment_inputs import _decode

    workbook = Workbook()
    sheet = workbook.active
    sheet.append([0, False, None, "value"])
    raw = io.BytesIO()
    workbook.save(raw)
    text, coverage = _decode(raw.getvalue(), ".xlsx")
    assert "0 | False |  | value" in text
    assert coverage["truncated"] is False
    sheet.cell(201, 1, "outside preview")
    raw = io.BytesIO()
    workbook.save(raw)
    text, coverage = _decode(raw.getvalue(), ".xlsx")
    assert "outside preview" not in text
    assert coverage["truncated"] is True
    assert coverage["max_rows_per_sheet"] == 200
    assert "部分" in coverage["notice"]


def test_text_preview_reports_character_limit():
    from app.application.agent_orchestrator.attachment_inputs import MAX_TEXT, _decode

    text, coverage = _decode(b"a" * (MAX_TEXT + 1), ".csv")
    assert len(text) == MAX_TEXT
    assert coverage["truncated"] is True
