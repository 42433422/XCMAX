"""Owned attachment boundary with real sessions, database rows and pinned file IO."""

import hashlib
import json
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
            assert db.query(EltUpload).filter(EltUpload.storage_path == str(shared)).count() == 0


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
            with workflow_file_snapshot(
                "price.csv", {**context, "attachment_upload_ids": ["missing"]}
            ):
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
    _, row = text.splitlines()
    assert row.startswith("[A1:D1] ")
    assert json.loads(row.split("] ", 1)[1]) == ["0", "False", "", "value"]
    assert coverage["truncated"] is False
    sheet.cell(201, 1, "outside preview")
    sheet.cell(2, 41, "outside column budget")
    raw = io.BytesIO()
    workbook.save(raw)
    text, coverage = _decode(raw.getvalue(), ".xlsx")
    assert "outside preview" not in text
    assert "outside column budget" not in text
    assert coverage["truncated"] is True
    assert coverage["max_rows_per_sheet"] == 200
    assert "部分" in coverage["notice"]


def test_workbook_preview_preserves_sparse_physical_addresses_and_sheet_boundaries():
    import io

    from openpyxl import Workbook

    from app.application.agent_orchestrator.attachment_inputs import _decode

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "First"
    sheet.merge_cells("B2:D2")
    sheet["B2"] = "Merged title"
    sheet["B4"] = "  spaced  "
    sheet["C4"] = "=1+1"
    sheet["D5"] = "multiline\nvalue | literal separator"
    second = workbook.create_sheet("Second")
    second["C1"] = "independent position"
    raw = io.BytesIO()
    workbook.save(raw)
    workbook.close()

    text, coverage = _decode(raw.getvalue(), ".xlsx")
    lines = text.splitlines()
    assert lines[0] == '[工作表] "First"'
    first = [line.split("] ", 1) for line in lines[1:6]]
    assert [address + "]" for address, _ in first] == [f"[A{r}:D{r}]" for r in range(1, 6)]
    assert json.loads(first[1][1]) == ["", "Merged title", "", ""]
    assert json.loads(first[2][1]) == ["", "", "", ""]
    assert json.loads(first[3][1]) == ["", "  spaced  ", "", ""]
    assert json.loads(first[4][1]) == ["", "", "", "multiline\nvalue | literal separator"]
    assert lines[6] == '[工作表] "Second"'
    assert lines[7].startswith("[A1:C1] ")
    assert json.loads(lines[7].split("] ", 1)[1]) == ["", "", "independent position"]
    assert coverage["truncated"] is False


def test_workbook_character_cap_never_returns_part_of_an_addressed_row():
    import io

    from openpyxl import Workbook

    from app.application.agent_orchestrator.attachment_inputs import MAX_TEXT, _decode

    workbook = Workbook()
    for _ in range(6):
        workbook.active.append(["x" * 500] * 40)
    raw = io.BytesIO()
    workbook.save(raw)
    workbook.close()

    text, coverage = _decode(raw.getvalue(), ".xlsx")
    assert coverage["truncated"] is True and len(text) <= MAX_TEXT
    header, row = text.splitlines()
    assert header.startswith("[工作表] ")
    assert row.startswith("[A1:AN1] ")
    assert json.loads(row.split("] ", 1)[1]) == ["x" * 500] * 40


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
    with pytest.raises(PermissionError):
        _read_snapshot(context, second["upload_id"], second)
    selected_second = {**context, "attachment_upload_ids": [second["upload_id"]]}
    assert _read_snapshot(selected_second, second["upload_id"], second) == 999


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
            pytest.raises(PermissionError, match="过期"),
            workflow_file_snapshot(first["upload_id"], context),
        ):
            pytest.fail("expired explicit ID must not produce a snapshot")
    with pytest.raises(PermissionError):
        _read_snapshot(context, second["upload_id"], second)
    selected_second = {**context, "attachment_upload_ids": [second["upload_id"]]}
    assert _read_snapshot(selected_second, second["upload_id"], second) == 999


def test_missing_bound_workbook_and_unregistered_path_fail_closed(duplicate_workbooks):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    context, first, _ = duplicate_workbooks
    missing = {**context, "attachment_upload_ids": ["missing-upload", first["upload_id"]]}
    unbound = {key: value for key, value in context.items() if key != "attachment_upload_ids"}
    with tenant_scope(int(context["tenant_id"])):
        for reference, runtime in (
            ("report.xlsx", missing),
            (first["upload_id"], missing),
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
                db.query(EltUpload.storage_path)
                .filter(EltUpload.id == second["upload_id"])
                .scalar()
            )
        with (
            pytest.raises(PermissionError, match="身份冲突"),
            workflow_file_snapshot(other_path, context),
        ):
            pytest.fail("a conflicting exact path must not replace the bound attachment")
    with pytest.raises(PermissionError):
        _read_snapshot(context, second["upload_id"], second)
    selected_second = {**context, "attachment_upload_ids": [second["upload_id"]]}
    assert _read_snapshot(selected_second, second["upload_id"], second) == 999


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


def _docx_bytes(document):
    import io

    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_chat_word_upload_binds_the_original_table_to_the_authenticated_turn(
    trusted_actor, monkeypatch, tmp_path
):
    import json

    from docx import Document
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import set_agent_run_repository_for_tests
    from app.application.agent_orchestrator.attachment_inputs import (
        AttachmentInputError,
        resolve_attachment_context,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.agent_runtime import goal_admission
    from app.application.agent_runtime.conversation_attachments import (
        EVIDENCE_SOURCE,
        recalled_attachment_view,
    )
    from app.application.agent_runtime.xiaox_runtime import _input_text
    from app.application.ai_chat.conversation_history import restore_runtime_history_files
    from app.application.task_conversation_store import TaskConversationStore
    from app.db.session import get_db
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
    from app.fastapi_routes.platform_shell_routes import router
    from app.infrastructure.xiaox.binding import XiaoxBinding, XiaoxBindingError, XiaoxBindingStore
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setattr(goal_admission, "_context_evidence", lambda *_: [])
    owner = trusted_actor()
    same_tenant = trusted_actor(tenant_id=owner.tenant_id)
    other_tenant = trusted_actor(tenant_id=owner.tenant_id + 1)
    document = Document()
    document.add_paragraph("对账单示例")
    document.add_table(rows=1, cols=2).rows[0].cells[1].text = "120.50"
    raw = _docx_bytes(document)
    form = {"file": ("对账单.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    path = "/api/platform-shell/chat-office-file-upload?attachment_only=true"
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as anonymous:
        assert anonymous.post(path, files=form).status_code == 401
    with TestClient(app, headers=owner.headers) as authenticated:
        assert authenticated.post(path, files={"file": ("arbitrary.txt", b"data")}).status_code == 400
        response = authenticated.post(path, files=form)
        assert response.status_code == 200, response.text
        unused = authenticated.post(path, files=form).json()["data"]["upload_id"]
    receipt = response.json()["data"]
    assert receipt.keys() == {"upload_id", "filename"}
    assert receipt["filename"] == "对账单.docx"
    assert not (tmp_path / "workspace").exists()
    attachments = {"attachment_upload_ids": [receipt["upload_id"]]}
    context, (artifact,) = resolve_attachment_context({**owner.context, **attachments})
    [verified] = context["file_context"]["verified_uploads"]
    assert verified["text"] == "对账单示例\n[表格 1 行 1 列 2] 120.50"
    assert artifact["source"] == "owned_elt_upload" and artifact["uri"] == ""
    assert artifact["metadata"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert artifact["metadata"]["skip_dataset_ingest"] is True
    for principal in (same_tenant, other_tenant):
        with pytest.raises(AttachmentInputError, match="附件不属于当前账户"):
            resolve_attachment_context({**principal.context, **attachments})

    repository = SQLAlchemyAgentRunRepository(session_factory=owner.factory)
    conversations = TaskConversationStore()
    book_chat, unrelated_chat = "book-chat", "unrelated-chat"
    with tenant_scope(owner.tenant_id):
        for session in (book_chat, unrelated_chat):
            conversations.save_message(session_id=session, user_id=owner.user_id, role="user", content="test")

    def chat_context(session, turn_id):
        return {**owner.context, "_conversation_revision": 0, "session_id": session,
                "conversation_id": session, "local_user_id": owner.user_id,
                "turn_id": turn_id, "execution_autonomy_level": 1}

    parent = AgentRun(str(owner.user_id), "读取附件", status="running")
    parent.metadata.update(
        runtime_type="xiaox", runtime_context=chat_context(book_chat, "original-turn")
    )
    contract = build_goal_contract(parent, attachments=[artifact])
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)
    bridge = XiaoxToolBridge(
        store, AgentOrchestrator(
            repository=repository, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
        )
    )
    set_agent_run_repository_for_tests(repository)
    try:
        selection = {"tool_id": "conversation_history", "action": "read_attachment"}
        discovery = bridge.invoke(grant.mcp_token, "capability_search", {"query": "docx 附件"})
        assert any(row["action"] == selection["action"] for row in discovery["capabilities"])
        spec = bridge.invoke(grant.mcp_token, "capability_describe", selection)["capability"]
        assert spec["read_only"] is True
        for requested in (receipt["upload_id"], unused):
            found = bridge.invoke(grant.mcp_token, "execute_action", {
                **selection, "params": {"upload_id": requested}, "call_id": requested,
                "schema_digest": spec["schema_digest"],
            })
            if requested == unused:
                assert found["status"] == "failed" and not found["verified"]
                assert "120.50" not in str(found)
            else:
                assert found["status"] == "completed" and found["verified"] is True, found
                [verified_step] = found["verification"]["steps"]
                assert verified_step["status"] == "verified"
                [tool] = found["tool_calls"]
                assert tool["output"]["data"]["text"] == verified["text"]
                assert tool["output"]["data"]["sha256"] == artifact["metadata"]["sha256"]

        def next_turn(session, fresh=False):
            current = AgentRun(str(owner.user_id), "查询另一个表格单元", status="running")
            current.metadata.update(runtime_type="xiaox", runtime_context=chat_context(session, current.run_id))
            if fresh:
                current.metadata["_xiaox_input_data"] = attachments
            frozen = goal_admission.prepare_runtime_goal(XiaoxBinding(current)).contract
            current.metadata.update(runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"])
            repository.save(current)
            return current, store.create(current.run_id).mcp_token, frozen["request"]

        continuation, token, followup = next_turn(book_chat)
        assert not followup["attachments"]
        [catalogue] = followup["context_evidence"]
        [entry] = catalogue["entries"]
        assert catalogue["source"] == EVIDENCE_SOURCE and entry["source_run_id"] == parent.run_id
        reference = entry["upload_id"]
        assert catalogue["verified_read"] == {
            **entry, "sha256": artifact["metadata"]["sha256"], **artifact["preview"],
        }

        conversation_context = continuation.metadata["runtime_context"]
        bound = continuation.metadata["runtime_goal_contract"]
        recalled_view = recalled_attachment_view(continuation, conversation_context)
        assert recalled_view == catalogue["verified_read"]
        assert "120.50" not in _input_text(continuation.message, [], None, goal=bound)
        assert "120.50" in _input_text(
            continuation.message, [], None, goal=bound, recalled_attachment=recalled_view
        )
        assert recalled_attachment_view(continuation, chat_context(unrelated_chat, "cross-chat")) is None
        assert recalled_attachment_view(continuation, {
            **conversation_context, **other_tenant.context,
        }) is None

        def read(token, value, call_id):
            return bridge.invoke(token, "execute_action", {
                **selection, "params": {"upload_id": value}, "call_id": call_id,
                "schema_digest": spec["schema_digest"],
            })

        recalled = read(token, reference, "recall-verified")
        assert recalled["status"] == "completed" and recalled["verified"], recalled
        assert recalled["tool_calls"][0]["output"]["data"]["text"] == verified["text"]
        assert read(token, receipt["upload_id"], "bare-id")["status"] == "failed"

        binding = {"run_id": parent.run_id, "turn_id": "original-turn", "recall_bound": True, "conversation_id": book_chat}
        page = {"messages": [{"role": "user", "metadata": json.dumps({"business_harness": binding, "summary": binding})}]}
        restore_runtime_history_files(page, {**parent.metadata["runtime_context"], "mod_id": ""})
        files = json.loads(page["messages"][0]["metadata"])["ui"]["inputAttachments"]
        assert files == [{"name": receipt["filename"], "reference": reference}]

        _, other_token, other = next_turn(unrelated_chat)
        assert not other["context_evidence"]
        with pytest.raises(XiaoxBindingError, match="未获授权"):
            read(other_token, reference, "different-session")
        _, fresh_token, fresh = next_turn(book_chat, fresh=True)
        assert fresh["attachments"] and not fresh["context_evidence"]
        assert read(fresh_token, reference, "old-after-current-selection")["status"] == "failed"

        # A second real selection leaves the catalogue available without guessing a file.
        alternate = AgentRun(str(owner.user_id), "另一个附件", status="running")
        alternate.metadata.update(runtime_type="xiaox", runtime_context=chat_context(book_chat, "second-turn"))
        _, artifacts = resolve_attachment_context({**owner.context, "attachment_upload_ids": [unused]})
        alternate_contract = build_goal_contract(alternate, attachments=artifacts)
        alternate.metadata.update(runtime_goal_contract=alternate_contract, runtime_goal_digest=alternate_contract["digest"])
        repository.save(alternate)
        _, _, ambiguous = next_turn(book_chat)
        [ambiguous_catalogue] = ambiguous["context_evidence"]
        assert len(ambiguous_catalogue["entries"]) == 2
        assert "verified_read" not in ambiguous_catalogue

        with tenant_scope(owner.tenant_id), get_db() as db:
            original = db.get(EltUpload, receipt["upload_id"])
            original.sha256 = "0" * 64
        assert recalled_attachment_view(continuation, conversation_context) is None
        with tenant_scope(owner.tenant_id), get_db() as db:
            original = db.get(EltUpload, receipt["upload_id"])
            original.sha256 = artifact["metadata"]["sha256"]
            original.expires_at = datetime(2000, 1, 1)
        assert recalled_attachment_view(continuation, conversation_context) is None
        assert read(token, reference, "expired-after-selection")["status"] == "failed"
        with tenant_scope(owner.tenant_id):
            conversations.delete_session(session_id=book_chat, user_id=owner.user_id)
        with pytest.raises(XiaoxBindingError, match="会话"):
            read(token, reference, "after-delete")
    finally:
        set_agent_run_repository_for_tests(None)


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


def test_inline_docx_distinguishes_footnote_reference_from_package_template():
    from docx import Document
    from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import OxmlElement

    from app.application.agent_orchestrator.attachment_inputs import _decode

    document = Document()
    paragraph = document.add_paragraph("Relevant body")
    footnotes = Part(
        PackURI("/word/footnotes.xml"), CONTENT_TYPE.WML_FOOTNOTES,
        b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        document.part.package,
    )
    document.part.relate_to(footnotes, RELATIONSHIP_TYPE.FOOTNOTES)
    raw = _docx_bytes(document)
    before = _decode(raw, ".docx")
    assert _decode(raw, ".docx", inline_context=True) == before

    paragraph.add_run()._r.append(OxmlElement("w:footnoteReference"))
    raw = _docx_bytes(document)
    assert _decode(raw, ".docx") == before
    assert _decode(raw, ".docx", inline_context=True)[1]["truncated"] is True


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


@pytest.mark.parametrize("scenario", ["ok", "broken", "large", "partial"])
def test_owned_docx_preview_uses_only_verified_upload(monkeypatch, scenario):
    import io
    from contextlib import nullcontext
    from unittest.mock import Mock

    from docx import Document

    from app.application.agent_orchestrator import attachment_inputs

    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "quoted value"
    if scenario == "partial":
        cell.add_table(rows=1, cols=1)
    raw = b"not a DOCX" if scenario == "broken" else _docx_bytes(document)
    row = SimpleNamespace(
        id="owned-file",
        file_name="quote.docx",
        suffix=".docx",
        storage_path="pinned-file",
        size_bytes=len(raw) if scenario != "large" else attachment_inputs._CONTEXT_FILE_BYTES + 1,
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

    if scenario == "large":
        assert attachment_inputs.resolve_attachment_inputs(context, inline_context=True) == []
        opened.assert_not_called()
        return
    if scenario == "partial":
        assert attachment_inputs.resolve_attachment_inputs(context, inline_context=True) == []
    elif scenario == "broken":
        with pytest.raises(attachment_inputs.AttachmentInputError, match="解析失败"):
            attachment_inputs.resolve_attachment_context(context)
    else:
        resolved, (artifact,) = attachment_inputs.resolve_attachment_context(context)
        assert artifact["source"] == "owned_elt_upload"
        assert artifact["metadata"]["upload_id"] == row.id
        assert artifact["preview"]["text"].strip() == "[表格 1 行 1 列 1] quoted value"
        assert resolved["file_context"] == {
            "verified_uploads": [
                {"name": row.file_name, "upload_id": row.id, **artifact["preview"]}
            ]
        }
    opened.assert_called_once_with(row.storage_path, owner_user_id=7)
