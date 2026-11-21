from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_template_analyze_agent_route import (
    template_runtime as template_runtime,
)
from tests.test_application.test_template_analyze_agent_route import (
    workbook_bytes,
)

_UPLOADS = [
    (
        "/api/templates/upload",
        {"name": "Office orders", "type": "excel", "source": "user_upload"},
        "Office orders",
        "",
        "user_upload",
    ),
    (
        "/api/templates/analyze",
        {"auto_save": "1", "template_name": "Office orders", "template_scope": "orders"},
        "Office orders",
        "orders",
        "templates_analyze_auto_save",
    ),
]


@pytest.mark.parametrize("path,form,name,scope,source", _UPLOADS)
def test_upload_waits_for_shared_approval_and_deduplicates_original_input(
    template_runtime, monkeypatch, path, form, name, scope, source
):
    actor, repo, client, inputs = template_runtime
    ingest = Mock()
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    content = workbook_bytes()
    headers = {**actor.headers, "Idempotency-Key": "original-office-upload"}
    first = client.post(
        path, files={"file": ("original.xlsx", content)}, data=form, headers=headers
    )
    assert first.status_code == 202, first.text
    run = repo.get(first.json()["run_id"])
    assert run.status == "waiting_user"
    assert run.steps[0].tool_id == "document_template"
    assert run.steps[0].action == "upload"
    params = run.steps[0].params
    assert params["template_name"] == name
    assert params["template_scope"] == scope
    assert params["source"] == source
    assert Path(params["file_path"]).read_bytes() == content
    assert run.tool_calls == []
    ingest.assert_not_called()

    retry = client.post(
        path, files={"file": ("original.xlsx", content)}, data=form, headers=headers
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["run_id"] == first.json()["run_id"]
    assert retry.json()["request_id"] == first.json()["request_id"]
    assert len(list(inputs.rglob("*.xlsx"))) == 1
    ingest.assert_not_called()

    canonical = client.post(
        "/api/tools/execute",
        json={"tool_id": "document_template", "action": "upload", "params": params},
        headers=headers,
    )
    assert canonical.status_code == 202, canonical.text
    assert canonical.json()["run_id"] == run.run_id
    assert canonical.json()["request_id"] == first.json()["request_id"]
    ingest.assert_not_called()

    conflict = client.post(
        path,
        files={"file": ("original.xlsx", workbook_bytes("Different input"))},
        data=form,
        headers=headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert Path(params["file_path"]).read_bytes() == content
    assert repo.get(run.run_id).tool_calls == []
    ingest.assert_not_called()


@pytest.mark.parametrize(
    "path,form",
    [
        ("/api/templates/analyze", {}),
        ("/api/templates/analyze", {"auto_save": "1"}),
        ("/api/templates/upload", {}),
    ],
)
def test_anonymous_template_input_is_not_persisted(template_runtime, monkeypatch, path, form):
    _, _, client, inputs = template_runtime
    ingest = Mock()
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    response = client.post(path, files={"file": ("private.xlsx", workbook_bytes())}, data=form)
    assert response.status_code == 401, response.text
    assert not list(inputs.rglob("*"))
    ingest.assert_not_called()


@pytest.mark.parametrize("path,form,name,scope,source", _UPLOADS)
def test_template_upload_requires_actual_template_permission(
    template_runtime, trusted_actor, monkeypatch, path, form, name, scope, source
):
    _, repo, client, _ = template_runtime
    actor = trusted_actor(role="without-template-grant", permissions=[])
    ingest = Mock()
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    response = client.post(
        path,
        files={"file": ("original.xlsx", workbook_bytes())},
        data=form,
        headers={**actor.headers, "Idempotency-Key": "missing-template-grant"},
    )
    assert response.status_code == 403, response.text
    assert not response.json().get("run_id")
    ingest.assert_not_called()


@pytest.mark.parametrize("operation", ["extract", "upload"])
@pytest.mark.parametrize("change", ["owner", "content"])
def test_shared_template_adapters_reject_foreign_or_changed_staged_input(
    template_runtime, trusted_actor, monkeypatch, operation, change
):
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_business_docking_family,
    )
    from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
        _registered_router_document_template,
    )
    from app.utils.path_io.upload_helpers import (
        _capability_upload_directory,
        stage_capability_upload,
    )

    actor, _, _, _ = template_runtime
    namespace = "template-analysis" if operation == "extract" else "document-template"
    receipt = stage_capability_upload(
        workbook_bytes(),
        "original.xlsx",
        actor.context,
        namespace=namespace,
        suffixes=frozenset({".xlsx"}),
    )
    path = _capability_upload_directory(actor.context, namespace) / receipt["saved_name"]
    context = actor.context
    if change == "owner":
        context = trusted_actor(role="admin").context
    else:
        path.write_bytes(workbook_bytes("Replaced content"))
    ingest = Mock()
    parse = Mock()
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    monkeypatch.setattr(
        "app.domain.shared_services.document_templates_service._extract_structured_excel_preview",
        parse,
    )
    router = (
        _registered_router_business_docking_family
        if operation == "extract"
        else _registered_router_document_template
    )
    result = router(operation, {"file_path": str(path)}, context, "admin", "")
    assert result["success"] is False
    assert result["error_code"] == "template_input_unavailable"
    assert result["execution_status"] == "not_started"
    ingest.assert_not_called()
    parse.assert_not_called()


def test_upload_rechecks_original_content_after_signed_approval(template_runtime, monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import (
        consume_approval_grant,
        issue_approval_grant,
    )

    actor, repo, client, _ = template_runtime
    ingest = Mock()
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    response = client.post(
        "/api/templates/upload",
        files={"file": ("original.xlsx", workbook_bytes())},
        headers={**actor.headers, "Idempotency-Key": "changed-before-approval"},
    )
    assert response.status_code == 202, response.text
    run = repo.get(response.json()["run_id"])
    Path(run.steps[0].params["file_path"]).write_bytes(workbook_bytes("Unapproved replacement"))
    with tenant_scope(actor.tenant_id):
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        claims = consume_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        done = AgentOrchestrator(repository=repo).continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            runtime_context=run.metadata["runtime_context"],
            approved_step_id=claims["step_id"],
            approval_request_id=run.metadata["approval_request_id"],
        )
    output = done.steps[0].output
    # The host conservatively requires reconciliation for any failed mutation
    # handler. It must retain the original pre-ingest rejection and never replay.
    assert output["error_code"] == "tool_result_unknown"
    assert output["reconciliation_evidence"]["error_code"] == "template_input_unavailable"
    assert output["reconciliation_evidence"]["execution_status"] == "not_started"
    assert output["retryable"] is False
    ingest.assert_not_called()
    replay = client.post(
        "/api/tools/execute",
        json={"tool_id": "document_template", "action": "upload", "params": run.steps[0].params},
        headers={**actor.headers, "Idempotency-Key": "changed-before-approval"},
    )
    assert replay.json()["run_id"] == run.run_id
    assert len(repo.get(run.run_id).tool_calls) == 1
    ingest.assert_not_called()


def test_approved_upload_forwards_owned_bytes_once_to_existing_ingest(
    template_runtime, monkeypatch
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import (
        consume_approval_grant,
        issue_approval_grant,
    )

    actor, repo, client, _ = template_runtime
    content = workbook_bytes()
    headers = {**actor.headers, "Idempotency-Key": "approved-template-upload"}
    ingest = Mock(
        return_value=({"success": False, "message": "original service rejected input"}, 400)
    )
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_bytes_to_template_library",
        ingest,
    )
    response = client.post(
        "/api/templates/upload",
        files={"file": ("original.xlsx", content)},
        data={"template_name": "Orders", "template_scope": "shipment", "source": "user_upload"},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    run = repo.get(response.json()["run_id"])
    ingest.assert_not_called()
    with tenant_scope(actor.tenant_id):
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        claims = consume_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        done = AgentOrchestrator(repository=repo).continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            approved_step_id=claims["step_id"],
            runtime_context=run.metadata["runtime_context"],
            approval_request_id=run.metadata["approval_request_id"],
        )
    ingest.assert_called_once_with(
        file_body=content,
        filename="original.xlsx",
        template_name="Orders",
        template_scope="shipment",
        source="user_upload",
    )
    assert done.steps[0].output["success"] is False
    assert len(done.tool_calls) == 1
    retry = client.post(
        "/api/templates/upload",
        files={"file": ("original.xlsx", content)},
        data={"template_name": "Orders", "template_scope": "shipment", "source": "user_upload"},
        headers=headers,
    )
    assert retry.json()["run_id"] == run.run_id
    assert retry.json()["success"] is False
    assert len(repo.get(run.run_id).tool_calls) == 1
    assert ingest.call_count == 1


def test_plain_workspace_template_path_keeps_existing_adapter(tmp_path, monkeypatch):
    from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
        _registered_router_document_template,
    )

    source = tmp_path / "ordinary.xlsx"
    source.write_bytes(workbook_bytes())
    ingest = Mock(return_value=({"success": False, "message": "observed original handler"}, 400))
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.ingest_office_path_to_template_library",
        ingest,
    )
    _registered_router_document_template("upload", {"file_path": str(source)}, {}, "admin", "")
    ingest.assert_called_once_with(
        str(source), template_name="", template_scope="", source="document_template_ingest"
    )
