"""Registered read capability with real sessions, receipts and native document bytes."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_document_fact_pages import write_document_fixture


@pytest.fixture
def owned_document(tmp_path, monkeypatch, trusted_actor):
    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.elt.service_uploads import register_chat_upload
    from app.application.tools import workflow

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    actor = trusted_actor(user_id=17, role="admin")
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    repo._ensure_schema()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    originals = tmp_path / "originals"
    originals.mkdir()
    mime = {
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }

    def upload(suffix, raw=None):
        source = originals / ("source" + suffix)
        if raw is None:
            write_document_fixture(source)
        else:
            source.write_bytes(raw)
        saved = register_chat_upload(
            user=SimpleNamespace(id=actor.user_id, tenant_id=actor.tenant_id),
            filename=source.name,
            content_type=mime[suffix],
            stream=io.BytesIO(source.read_bytes()),
        )
        return source, saved

    counter = 0

    def execute(params, context=None, *, action="read"):
        nonlocal counter
        counter += 1
        result = json.loads(
            workflow.execute_workflow_tool(
                workflow.ERP_CAPABILITY_TOOL_NAME,
                {"tool_id": "excel_analysis", "action": action, "params": params},
                runtime_context={
                    **(context or actor.context),
                    "idempotency_key": f"document-page-{counter}",
                },
            )
        )
        run = repo.get(result["run_id"]) if result.get("run_id") else None
        output = run.steps[0].output if run is not None and run.steps else result
        return result, output, run

    def route(params, *, action="read"):
        from app.domain.shared_services.tools_workflow_excel_ocr import (
            _registered_router_excel_analysis,
        )

        # A parent-side parser probe cannot observe the real spawn worker used
        # above. Keep this authorization-order probe at the registered router;
        # the format roundtrips still exercise the actual isolated capability.
        with tenant_scope(actor.tenant_id):
            return _registered_router_excel_analysis(action, params, actor.context, "shared", "")

    return SimpleNamespace(actor=actor, upload=upload, execute=execute, route=route, repo=repo)


@pytest.mark.parametrize("suffix", [".csv", ".tsv", ".docx", ".pptx", ".pdf"])
def test_registered_native_document_pages_and_exact_cell_readback(owned_document, suffix):
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    original, upload = owned_document.upload(suffix)
    envelope, tables, run = owned_document.execute(
        {"file_path": upload["upload_id"], "view": "tables"}
    )
    assert envelope["success"] is True and tables["success"] is True, (envelope, tables)
    assert run.status == "completed" and run.user_id == str(owned_document.actor.user_id)
    assert get_tool_action_spec("excel_analysis", "read").read_only is True
    assert (
        tables["data"]["source_sha256"]
        == upload["sha256"]
        == hashlib.sha256(original.read_bytes()).hexdigest()
    )
    table = tables["data"]["items"][0]
    assert table["cell_count"] == 4 and "cells" not in table
    args = {"file_path": upload["upload_id"], **table["readback"], "max_rows": 2}
    _, first, _ = owned_document.execute(args)
    assert first["success"] is True and first["data"]["has_more"] is True
    _, second, _ = owned_document.execute(
        {**args, "cursor": first["data"]["next_cursor"], "offset": first["data"]["next_offset"]}
    )
    assert second["success"] is True and second["data"]["has_more"] is False
    assert [cell["value"] for cell in second["data"]["items"]] == (
        ["line1\nline2", "0"] if suffix in {".csv", ".tsv"} else ["0", "retained"]
    )
    cell = second["data"]["items"][-1]
    _, exact, _ = owned_document.execute(
        {
            "file_path": upload["upload_id"],
            "view": "cells",
            "fact_id": cell["cell_id"],
            "expected_sha256": upload["sha256"],
        }
    )
    assert exact["data"]["items"] == [cell]
    assert len(json.dumps(exact, ensure_ascii=False, separators=(",", ":")).encode()) <= 40_000
    assert "input" + suffix not in exact["file_path"]
    if suffix == ".pdf":
        assert exact["data"]["source_status"] == "partial"
        assert exact["data"]["partial"] is True
        assert {"code": "page_2_requires_ocr"} in exact["data"]["warnings"]


@pytest.mark.parametrize("suffix", [".pptx", ".pdf"])
def test_registered_pages_and_regions_keep_native_page_locations(owned_document, suffix):
    _, upload = owned_document.upload(suffix)
    args = {"file_path": upload["upload_id"], "view": "pages", "max_rows": 1}
    _, first, _ = owned_document.execute(args)
    assert first["success"] is True and first["data"]["known_total"] == 2
    _, second, _ = owned_document.execute(
        {**args, "cursor": first["data"]["next_cursor"], "expected_sha256": upload["sha256"]}
    )
    assert second["data"]["items"][0]["source_ref"]["page"] == 2
    assert second["data"]["has_more"] is False
    _, regions, _ = owned_document.execute(
        {"file_path": upload["upload_id"], "view": "regions", "page": 1}
    )
    assert regions["success"] is True and regions["data"]["items"]
    for region in regions["data"]["items"]:
        assert isinstance(region["region_id"], str) and region["region_id"]
        assert region["source_ref"]["page"] == 1 and region["source_ref"]["bbox"]
    region = regions["data"]["items"][0]
    _, exact, _ = owned_document.execute(
        {
            "file_path": upload["upload_id"],
            "view": "regions",
            "fact_id": region["region_id"],
            "expected_sha256": upload["sha256"],
        }
    )
    assert exact["data"]["items"] == [region]


@pytest.mark.parametrize(
    "change", ["owner", "tenant", "upload_expiry", "tampered", "replacement", "session_expiry"]
)
def test_every_registered_continuation_rechecks_ownership_expiry_and_source(
    owned_document, monkeypatch, change
):
    from app.db.models.elt import EltUpload
    from app.db.models.user import Session as UserSession
    from app.infrastructure.document_parsing import native

    _, upload = owned_document.upload(".csv")
    parse = Mock(wraps=native._delimited)
    monkeypatch.setattr(native, "_delimited", parse)
    args = {"file_path": upload["upload_id"], "view": "cells", "max_rows": 1}
    first = owned_document.route(args)
    assert first["success"] is True and parse.call_count == 1
    actor = owned_document.actor
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        row = db.get(EltUpload, upload["upload_id"])
        assert row is not None
        if change in {"tampered", "replacement"}:
            path = Path(row.storage_path)
            path.chmod(0o600)
            body = b"A,A\nchanged,1\n"
            path.write_bytes(body)
            if change == "replacement":
                row.sha256, row.size_bytes = hashlib.sha256(body).hexdigest(), len(body)
        elif change == "session_expiry":
            db.get(UserSession, actor.session_row_id).expires_at = datetime(2000, 1, 1)
        else:
            key, value = {
                "owner": ("owner_user_id", 99),
                "tenant": ("tenant_id", 99),
                "upload_expiry": ("expires_at", datetime(2000, 1, 1)),
            }[change]
            setattr(row, key, value)
    rejected = owned_document.route(
        {**args, "cursor": first["data"]["next_cursor"], "expected_sha256": upload["sha256"]}
    )
    assert rejected["success"] is False, rejected
    assert "items" not in (rejected.get("data") or {}) and parse.call_count == 1
    if change == "replacement":
        assert rejected["error_code"] == "document_source_changed"


def test_same_source_cursor_cannot_transfer_to_another_real_session(owned_document, trusted_actor):
    _, upload = owned_document.upload(".csv")
    args = {"file_path": upload["upload_id"], "view": "cells", "max_rows": 1}
    _, first, _ = owned_document.execute(args)
    other = trusted_actor(user_id=owned_document.actor.user_id, role="admin")
    resume = {**args, "cursor": first["data"]["next_cursor"], "expected_sha256": upload["sha256"]}
    _, denied, _ = owned_document.execute(resume, other.context)
    assert (
        denied["success"] is False
        and denied["error_code"] == "document_cursor_source_or_scope_changed"
    )
    _, fresh, _ = owned_document.execute(args, other.context)
    assert fresh["success"] is True
    assert fresh["data"]["document_id"] != first["data"]["document_id"]
    _, forged, _ = owned_document.execute(
        {**resume, "authorization_scope": first["data"]["source_ref"]["authorization_scope"]},
        other.context,
    )
    assert forged["success"] is False and forged["error_code"] == "document_argument_not_supported"


def test_registered_read_rejects_oversized_item_and_unavailable_structure(owned_document):
    _, large = owned_document.upload(".csv", ("字" * 14_000).encode())
    _, result, _ = owned_document.execute({"file_path": large["upload_id"], "view": "cells"})
    assert result["success"] is False and result["status"] == "blocked"
    assert result["error_code"] == "document_item_budget_exceeded" and "data" not in result
    _, word = owned_document.upload(".docx")
    _, result, _ = owned_document.execute({"file_path": word["upload_id"], "view": "pages"})
    assert result["success"] is False and result["status"] == "unsupported"


@pytest.mark.parametrize("suffix", [".json", ".txt", ".png"])
def test_new_owner_bound_artifact_kinds_never_bypass_current_actor(
    trusted_actor, tmp_path, monkeypatch, suffix
):
    from PIL import Image

    from app.application.agent_orchestrator.artifact_files import store_run_file
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner = trusted_actor(role="admin")
    stranger = trusted_actor(role="admin")
    if suffix == ".png":
        raw = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(raw, format="PNG")
        body = raw.getvalue()
    else:
        body = b'{"zero":0,"flag":false}' if suffix == ".json" else b"retained"
    run_id = "document-page-owner-test"
    receipt = store_run_file(
        run_id,
        body,
        name="source" + suffix,
        owner_user_id=owner.user_id,
        tenant_id=str(owner.tenant_id),
    )
    context = {
        **owner.context,
        "run_id": run_id,
        "node_outputs": {"original": {"success": True, "artifacts": [receipt]}},
    }
    with tenant_scope(owner.tenant_id), workflow_file_snapshot(receipt["uri"], context) as snapshot:
        assert snapshot.read_bytes() == body
    foreign = {**context, **stranger.context}
    with tenant_scope(stranger.tenant_id):
        with pytest.raises(PermissionError), workflow_file_snapshot(receipt["uri"], foreign):
            pytest.fail("another account received the owner-bound source")
    if suffix == ".json":
        with tenant_scope(owner.tenant_id):
            result = _registered_router_excel_analysis(
                "read", {"file_path": receipt["uri"], "view": "regions"}, context, "shared", ""
            )
        assert result["success"] is True
        values = {item["source_ref"]["json_pointer"]: item for item in result["data"]["items"]}
        assert values["/zero"]["value"] == 0 and values["/flag"]["value"] is False
    receipt["metadata"].pop("owner_user_id")
    with tenant_scope(owner.tenant_id):
        with pytest.raises(PermissionError), workflow_file_snapshot(receipt["uri"], context):
            pytest.fail("an ownerless legacy receipt authorized the new read")
