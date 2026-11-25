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
        root = tmp_path / "elt" / "uploads" / principal.tenant_id / principal.user_id
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


def test_unregistered_legacy_upload_is_never_adopted(owned, monkeypatch, tmp_path):
    context, _ = owned
    shared = tmp_path / "uploads" / "foreign.csv"
    shared.parent.mkdir()
    shared.write_text("secret,42\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.get_app_data_dir",
        lambda: str(tmp_path),
    )
    from app.application.tools.workflow_spreadsheet_scope import resolve_owned_upload_path
    from app.db.session import get_db

    with tenant_scope(int(context["tenant_id"])):
        assert resolve_owned_upload_path("uploads/foreign.csv", context) == "uploads/foreign.csv"
        with get_db() as db:
            assert db.query(EltUpload).filter(EltUpload.storage_path == str(shared)).count() == 0


def test_prefixed_chat_upload_path_resolves_by_original_file_name(owned):
    context, file = owned
    from app.application.tools.workflow_spreadsheet_scope import resolve_owned_upload_path

    with tenant_scope(int(context["tenant_id"])):
        assert (
            resolve_owned_upload_path("uploads/chat/7a9193dba432-price.csv", context)
            == str(file)
        )


def test_selected_upload_does_not_switch_to_newer_same_name(owned):
    import io

    from app.application.elt.service_uploads import register_chat_upload
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    context, original = owned
    user = SimpleNamespace(id=int(context["user_id"]), tenant_id=int(context["tenant_id"]))
    register_chat_upload(
        user=user,
        filename="price.csv",
        content_type="text/csv",
        stream=io.BytesIO(b"product,price\nnewer,500\n"),
    )
    with tenant_scope(int(context["tenant_id"])):
        with workflow_file_snapshot("price.csv", context) as snapshot:
            assert snapshot.read_bytes() == original.read_bytes()
        with pytest.raises(PermissionError):
            with workflow_file_snapshot("price.csv", {**context, "attachment_upload_ids": ["missing"]}):
                pytest.fail("missing selected attachment must not fall back to another upload")


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


def _docx_bytes(document):
    import io

    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_docx_preview_keeps_body_order_and_cell_coordinates():
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    document.add_paragraph("Introduction")
    table = document.add_table(rows=3, cols=4)
    table.cell(0, 0).text = "SKU | Item"
    table.cell(0, 2).merge(table.cell(0, 3)).text = "Quoted price"
    table.cell(1, 0).merge(table.cell(2, 0)).text = "Paint"
    table.cell(1, 2).text = "0"
    table.cell(2, 2).text = "120"
    row = table.rows[2]._tr
    row.remove(row.tc_lst[0])
    before = OxmlElement("w:gridBefore")
    before.set(qn("w:val"), "1")
    row.get_or_add_trPr().append(before)
    document.add_paragraph("Terms")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Net 30"

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text.splitlines() == [
        "Introduction",
        "[表格 1 行 1 列 1] SKU | Item",
        "[表格 1 行 1 列 3] Quoted price",
        "[表格 1 行 2 列 1] Paint",
        "[表格 1 行 2 列 3] 0",
        "[表格 1 行 3 列 3] 120",
        "Terms",
        "[表格 2 行 1 列 1] Net 30",
    ]
    assert coverage["scope"] == "paragraphs_and_tables"
    assert coverage["truncated"] is False


def test_docx_preview_marks_nested_table_omission_without_misattribution():
    from docx import Document

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    outer = document.add_table(rows=1, cols=1).cell(0, 0)
    outer.text = "parent cell"
    outer.add_table(rows=1, cols=1).cell(0, 0).text = "nested only"

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text.strip() == "[表格 1 行 1 列 1] parent cell"
    assert coverage["truncated"] is True


def test_docx_preview_reports_omitted_content_control():
    from docx import Document
    from docx.oxml import OxmlElement

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    document.add_paragraph("visible")
    wrapped = document.add_paragraph("wrapped content")._p
    control = OxmlElement("w:sdt")
    content = OxmlElement("w:sdtContent")
    control.append(content)
    wrapped.addprevious(control)
    content.append(wrapped)

    text, coverage = _decode(_docx_bytes(document), ".docx")
    assert text == "visible"
    assert coverage["truncated"] is True


def test_docx_preview_rejects_oversized_expanded_package():
    import io
    from zipfile import ZIP_DEFLATED, ZipFile

    from docx import Document

    from app.application.agent_orchestrator.attachment_inputs import AttachmentInputError, _decode

    stream = io.BytesIO(_docx_bytes(Document()))
    with ZipFile(stream, "a", ZIP_DEFLATED) as archive:
        archive.writestr("word/unused.bin", b"\0" * (32 * 1024 * 1024))

    with pytest.raises(AttachmentInputError, match="体积过大"):
        _decode(stream.getvalue(), ".docx")


@pytest.mark.parametrize("broken", [False, True])
def test_owned_docx_preview_uses_only_verified_upload(monkeypatch, broken):
    import io
    from contextlib import nullcontext
    from unittest.mock import Mock

    from docx import Document

    from app.application.agent_orchestrator import attachment_inputs

    document = Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = "quoted value"
    raw = b"not a DOCX" if broken else _docx_bytes(document)
    row = SimpleNamespace(
        id="owned-file",
        file_name="quote.docx",
        suffix=".docx",
        storage_path="pinned-file",
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = row
    opened = Mock(return_value=io.BytesIO(raw))
    monkeypatch.setattr(attachment_inputs, "get_db", lambda: nullcontext(db))
    monkeypatch.setattr(attachment_inputs, "tenant_scope", lambda _: nullcontext())
    monkeypatch.setattr(attachment_inputs, "validate_actor_context", lambda _: None)
    monkeypatch.setattr(attachment_inputs, "open_elt_input_file", opened)
    context = {
        "user_id": 7,
        "tenant_id": 13,
        "attachment_upload_ids": [row.id],
        "file_context": {"verified_uploads": [{"text": "untrusted fallback"}]},
    }

    if broken:
        with pytest.raises(attachment_inputs.AttachmentInputError, match="解析失败"):
            attachment_inputs.resolve_attachment_context(context)
    else:
        resolved, (artifact,) = attachment_inputs.resolve_attachment_context(context)
        assert artifact["source"] == "owned_elt_upload"
        assert artifact["metadata"]["upload_id"] == row.id
        assert artifact["preview"]["text"].strip() == "[表格 1 行 1 列 1] quoted value"
        assert resolved["file_context"] == {
            "verified_uploads": [{"name": row.file_name, **artifact["preview"]}]
        }
    opened.assert_called_once_with(row.storage_path, owner_user_id=7)
