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
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def owned(monkeypatch, tmp_path):
    from app.utils.path_io import path_utils

    monkeypatch.setattr(path_utils, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.get_app_data_dir",
        lambda: str(tmp_path),
    )
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
            assert (
                db.query(EltUpload).filter(EltUpload.storage_path == str(shared)).count() == 0
            )


def test_prefixed_chat_upload_path_resolves_by_original_file_name(
    trusted_actor, monkeypatch, tmp_path
):
    """Use the real route's random path, never invent a prefix in the positive control."""
    import io
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openpyxl import Workbook

    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.fastapi_routes.platform_shell_routes import router

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    actor = trusted_actor(permissions=["employee.execute", "tool.excel_analysis.read"])
    app = FastAPI()
    app.include_router(router)
    originals = []
    receipts = []
    with TestClient(app, headers=actor.headers) as client:
        for amount in (120, 999):
            book = Workbook()
            book.active.append(["product", "amount"])
            book.active.append(["paint", amount])
            with io.BytesIO() as stream:
                book.save(stream)
                original = stream.getvalue()
            book.close()
            response = client.post(
                "/api/platform-shell/chat-office-file-upload",
                files={
                    "file": (
                        "report.xlsx",
                        original,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
            assert response.status_code == 200, response.text
            receipts.append(response.json()["data"])
            originals.append(original)
    first, second = receipts
    assert first["upload_id"] != second["upload_id"]
    legacy_path = first["file_path"]
    assert legacy_path.startswith("uploads/chat/")
    assert Path(legacy_path).name.endswith("-report.xlsx")
    assert legacy_path != second["file_path"]
    context = {**actor.context, "attachment_upload_ids": [first["upload_id"]]}
    with tenant_scope(actor.tenant_id):
        for reference in (first["upload_id"], legacy_path, "report.xlsx"):
            with workflow_file_snapshot(reference, context) as snapshot:
                assert snapshot.read_bytes() == originals[0]
        with workflow_file_snapshot(second["upload_id"], actor.context) as snapshot:
            assert snapshot.read_bytes() == originals[1]
        for reference in (legacy_path, "report.xlsx"):
            with pytest.raises(PermissionError), workflow_file_snapshot(reference, actor.context):
                pytest.fail("an unbound random path or ambiguous name is not an upload identity")


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


@pytest.fixture
def duplicate_workbooks(owned):
    import io

    from openpyxl import Workbook

    from app.application.elt.service_uploads import register_chat_upload

    context, _ = owned
    user = SimpleNamespace(id=int(context["user_id"]), tenant_id=int(context["tenant_id"]))
    receipts = []
    for amount in (120, 999):
        workbook = Workbook()
        workbook.active.append(["product", "amount"])
        workbook.active.append(["paint", amount])
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        stream.seek(0)
        receipts.append(
            register_chat_upload(
                user=user,
                filename="report.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                stream=stream,
            )
        )
    return context, receipts[0], receipts[1]


def _read_snapshot(context, reference, receipt):
    from openpyxl import load_workbook

    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    with (
        tenant_scope(int(context["tenant_id"])),
        workflow_file_snapshot(reference, context) as snapshot,
    ):
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == receipt["sha256"]
        workbook = load_workbook(snapshot, read_only=True, data_only=True)
        try:
            return workbook.active["B2"].value
        finally:
            workbook.close()


def test_current_workbook_attachment_is_pinned_despite_newer_same_name(duplicate_workbooks):
    from app.application.agent_orchestrator.attachment_inputs import resolve_attachment_context

    context, first, second = duplicate_workbooks
    assert first["upload_id"] != second["upload_id"]
    assert first["sha256"] != second["sha256"]
    context = {**context, "attachment_upload_ids": [first["upload_id"]]}
    context, _ = resolve_attachment_context(context)
    assert context["file_context"]["verified_uploads"][0]["upload_id"] == first["upload_id"]
    assert _read_snapshot(context, "report.xlsx", first) == 120
    assert _read_snapshot(context, "uploads/chat/7a9193dba432-report.xlsx", first) == 120
    assert _read_snapshot(context, second["upload_id"], second) == 999


def test_same_name_is_ambiguous_without_unique_conversation_binding(duplicate_workbooks):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    context, first, second = duplicate_workbooks
    unbound = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    both = {**context, "attachment_upload_ids": [first["upload_id"], second["upload_id"]]}
    with tenant_scope(int(context["tenant_id"])):
        for runtime in (unbound, both):
            with (
                pytest.raises(PermissionError, match="多个同名"),
                workflow_file_snapshot("report.xlsx", runtime),
            ):
                pytest.fail("ambiguous filename must not produce a snapshot")
    assert _read_snapshot(both, first["upload_id"], first) == 120


def test_followup_reuses_original_excel_reference(duplicate_workbooks):
    context, first, _ = duplicate_workbooks
    context = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    original_path = "uploads/chat/7a9193dba432-report.xlsx"
    context["last_excel_analysis_context"] = {
        "excel_analysis": {"file_path": original_path, "upload_id": first["upload_id"]}
    }
    assert _read_snapshot(context, original_path, first) == 120
    assert _read_snapshot(context, "report.xlsx", first) == 120


def test_expired_bound_workbook_never_falls_back_to_newer_upload(duplicate_workbooks):
    from app.application.elt.errors import EltError
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.db.session import get_db

    context, first, second = duplicate_workbooks
    context = {**context, "attachment_upload_ids": [first["upload_id"]]}
    with tenant_scope(int(context["tenant_id"])):
        with get_db() as db:
            row = db.query(EltUpload).filter(EltUpload.id == first["upload_id"]).one()
            row.expires_at = datetime(2000, 1, 1)
        for reference in ("report.xlsx", "uploads/chat/7a9193dba432-report.xlsx"):
            with (
                pytest.raises(PermissionError, match="过期"),
                workflow_file_snapshot(reference, context),
            ):
                pytest.fail("expired bound attachment must not produce a snapshot")
        with (
            pytest.raises(EltError, match="过期"),
            workflow_file_snapshot(first["upload_id"], context),
        ):
            pytest.fail("expired explicit ID must not produce a snapshot")
    assert _read_snapshot(context, second["upload_id"], second) == 999


def test_missing_bound_workbook_and_unregistered_path_fail_closed(duplicate_workbooks):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    context, first, _ = duplicate_workbooks
    missing = {**context, "attachment_upload_ids": ["missing-upload", first["upload_id"]]}
    unbound = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    with tenant_scope(int(context["tenant_id"])):
        for reference, runtime in (
            ("report.xlsx", missing),
            ("uploads/chat/unknown-report.xlsx", unbound),
        ):
            with pytest.raises(PermissionError), workflow_file_snapshot(reference, runtime):
                pytest.fail("unbound or missing attachment must not produce a snapshot")


def test_verified_workbook_reader_and_result_receipt(duplicate_workbooks, monkeypatch, tmp_path):
    import io

    from openpyxl import Workbook, load_workbook

    from app.application.agent_orchestrator.artifact_files import (
        read_verified_run_file,
        store_scoped_run_file,
    )
    from app.application.tools.workflow_spreadsheet_scope import office_reader_input

    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.get_app_data_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir", lambda: str(tmp_path)
    )
    context, first, _ = duplicate_workbooks
    context = {
        **context,
        "attachment_upload_ids": [first["upload_id"]],
        "run_id": "xlsx-identity-regression",
        "step_id": "read",
        "node_id": "read",
        "call_id": "read-1",
        "input_sha256": first["sha256"],
    }
    with (
        tenant_scope(int(context["tenant_id"])),
        office_reader_input(
            "excel-full-read-employee", {"file_path": "report.xlsx"}, context
        ) as payload,
    ):
        source = load_workbook(payload["file_path"], read_only=True, data_only=True)
        try:
            result = Workbook()
            result.active.append(["verified_amount", source.active["B2"].value])
            output = io.BytesIO()
            result.save(output)
            result.close()
        finally:
            source.close()
        receipt = store_scoped_run_file(output.getvalue(), name="result.xlsx", context=context)
    raw = read_verified_run_file(context["run_id"], receipt)
    assert hashlib.sha256(raw).hexdigest() == receipt["metadata"]["sha256"]
    verified = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        assert verified.active["B1"].value == 120
    finally:
        verified.close()


def test_exact_path_cannot_override_same_name_conversation_binding(duplicate_workbooks):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.db.session import get_db

    context, first, second = duplicate_workbooks
    context = {**context, "attachment_upload_ids": [first["upload_id"]]}
    with tenant_scope(int(context["tenant_id"])):
        with get_db() as db:
            other_path = (
                db.query(EltUpload.storage_path).filter(EltUpload.id == second["upload_id"]).scalar()
            )
        with (
            pytest.raises(PermissionError, match="身份冲突"),
            workflow_file_snapshot(other_path, context),
        ):
            pytest.fail("a conflicting exact path must not replace the bound attachment")
    assert _read_snapshot(context, second["upload_id"], second) == 999

@pytest.mark.parametrize("foreign_field", ["owner_user_id", "tenant_id"])
@pytest.mark.parametrize("reference", ["owned-file", "price.csv", "7a9193dba432-price.csv"])
def test_foreign_account_or_tenant_cannot_resolve_id_or_name(owned, foreign_field, reference):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.db.session import get_db

    context, _ = owned
    # The absence of a conversation binding must not broaden account or tenant scope.
    unbound = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    with tenant_scope(int(context["tenant_id"])):
        with get_db() as db:
            row = db.query(EltUpload).filter(EltUpload.id == "owned-file").one()
            setattr(row, foreign_field, int(getattr(row, foreign_field)) + 1000)
        with pytest.raises(PermissionError, match="文件不属于"):
            with workflow_file_snapshot(reference, unbound):
                pytest.fail("a foreign upload must never be adopted by ID or filename")


def test_expired_unbound_filename_does_not_resolve(owned):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.db.session import get_db

    context, _ = owned
    unbound = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    with tenant_scope(int(context["tenant_id"])):
        with get_db() as db:
            row = db.query(EltUpload).filter(EltUpload.id == "owned-file").one()
            row.expires_at = datetime(2000, 1, 1)
        with pytest.raises(PermissionError, match="文件不属于"):
            with workflow_file_snapshot("price.csv", unbound):
                pytest.fail("an expired upload must never match a bare filename")
