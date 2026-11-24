"""Original template writes, reloadable readback and fail-closed tenant/file proof."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_permission import idempotency_scope_key
from app.application.agent_orchestrator.verification_readback import verify_independent_result
from tests.test_routes.test_template_create_default_app import (
    _label_payload,
    _post,
)
from tests.test_routes.test_template_create_default_app import (
    template_app as template_app,
)


def _case(repo, run_id):
    run = repo.get(run_id)
    step, call = run.steps[0], run.tool_calls[-1]
    context = {
        **run.metadata["runtime_context"],
        **task_execution_context(run, step),
        "run_id": run.run_id,
        "step_id": step.step_id,
    }
    key = idempotency_scope_key(context, step.tool_id, step.action, step.params)
    return SimpleNamespace(run=run, step=step, call=call, context=context, key=key)


def _verify(case):
    return verify_independent_result(
        run=case.run, step=case.step, call=case.call, context=case.context, output=case.call.output
    )


def test_template_create_update_and_recovery_read_only_original_transaction(
    template_app, monkeypatch
):
    client, engine, repo = template_app
    headers = {"X-Session-ID": "label-session-7"}
    created = _post(client, "/api/templates/create", headers=headers, json=_label_payload())
    assert created.status_code == 200, created.text
    first = _case(repo, created.json()["run_id"])
    assert _verify(first)["status"] == "verified"
    # Updates are exposed by the existing opt-in system router, not the default factory.
    from app.fastapi_routes.domains.system.system_routes import router

    client.app.include_router(router)
    updated = _post(client, 
        "/api/templates/update",
        headers=headers,
        json={"id": created.json()["template"]["id"], "name": "Updated label"},
    )
    assert updated.status_code == 200, updated.text
    case = _case(repo, updated.json()["run_id"])
    original = copy.deepcopy(case.call.output)
    statements = []

    def observed(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    def no_hydration(*_args, **_kwargs):
        raise AssertionError("readback must not hydrate, scan, or execute templates")

    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.FileSystemTemplateStore.list_templates",
        no_hydration,
    )
    monkeypatch.setattr(
        "app.legacy.routes.document_templates_compat.run_archive_template_update", no_hydration
    )
    event.listen(engine, "before_cursor_execute", observed)
    try:
        for _ in range(2):
            report = _verify(case)
            assert report["status"] == "verified", report
            assert report["checks"][0]["evidence"]["scope"] == "template_current_state"
        assert _verify(first)["code"] == "result_template_state_mismatch"
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert not {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"} & set(statements)
    assert case.call.output == original
    assert repo.get(case.run.run_id).status == "completed"


def test_reviewed_template_reuse_commits_original_receipt_without_second_template(
    template_app, tmp_path
):
    from openpyxl import Workbook

    client, engine, repo = template_app
    path = tmp_path / "templates/reviewed_excel/11/reviewed.xlsx"
    path.parent.mkdir(parents=True)
    workbook = Workbook()
    workbook.active.append(["产品名称", "数量"])
    workbook.save(path)
    workbook.close()
    payload = {
        **_label_payload(),
        "template_type": "Excel",
        "category": "excel",
        "source": "reviewed_excel_cleanup",
        "file_path": str(path),
        "preview_data": {"reviewed_excel": True},
    }
    first = _post(client, 
        "/api/templates/create", headers={"X-Session-ID": "label-session-7"}, json=payload
    )
    second = _post(client, 
        "/api/templates/create",
        headers={"X-Session-ID": "label-session-7"},
        json={**payload, "name": "Another request for the same reviewed layout"},
    )
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert second.json()["reused"] is True
    assert first.json()["template"]["id"] == second.json()["template"]["id"]
    assert first.json()["run_id"] != second.json()["run_id"]
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM task_lifecycle_records WHERE module='document_template_mutation'"
                )
            ).scalar_one()
            == 2
        )
    for response in (first, second):
        assert _verify(_case(repo, response.json()["run_id"]))["status"] == "verified"


def test_authenticated_analyze_create_and_preview_keep_original_tenant_file(template_app, tmp_path):
    from app.application.office_template_ingest_app_service import (
        _build_create_payload_from_analyze,
    )

    client, engine, repo = template_app
    content = "产品名称,数量\n已上传产品,2\n".encode()
    headers = {"X-Session-ID": "label-session-7", "X-Tenant-ID": "22", "X-User-Id": "8"}
    analyzed = _post(client, 
        "/api/templates/analyze",
        headers=headers,
        files={"file": ("source.csv", content, "text/csv")},
        data={"template_name": "Owned upload", "tenant_id": "22"},
    )
    assert analyzed.status_code == 200, analyzed.text
    path = Path(analyzed.json()["preview_data"]["file_path"])
    assert path.parent == tmp_path / "tenants/11/document_templates"
    assert path.read_bytes() == content
    payload = _build_create_payload_from_analyze(analyzed.json(), filename="source.csv")
    created = _post(client, "/api/templates/create", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    case = _case(repo, created.json()["run_id"])
    assert _verify(case)["status"] == "verified"
    assert case.run.user_id == "7" and case.context["tenant_id"] == "11"
    file_url = f"/api/templates/{created.json()['template']['id']}/file"
    owner_download = client.get(file_url, headers={"X-Session-ID": "label-session-7"})
    assert owner_download.status_code == 200, owner_download.text
    assert owner_download.content == content
    assert client.get(file_url, headers={"X-Session-ID": "label-session-8"}).status_code == 404
    shared = tmp_path / "uploads/templates/legacy.csv"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(content)
    for session, source in (("label-session-8", path), ("label-session-7", shared)):
        refused = _post(client, 
            "/api/templates/create",
            headers={"X-Session-ID": session},
            json={**payload, "file_path": str(source), "original_file_path": str(source)},
        )
        assert refused.status_code == 202, refused.text
        assert refused.json()["success"] is False
        refused_run = repo.get(refused.json()["run_id"])
        assert refused_run.status == "blocked"
        assert refused_run.tool_calls[-1].metadata["verification"]["accepted"] is False
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
    assert path.read_bytes() == shared.read_bytes() == content


@pytest.mark.parametrize(
    "changed", ["row", "tenant", "binding", "database_receipt", "tool_receipt", "bytes", "path"]
)
def test_template_readback_rejects_missing_original_receipts_and_changed_scope(
    template_app, tmp_path, changed
):
    client, engine, repo = template_app
    path = tmp_path / "tenants/11/templates/private.xlsx"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"original archived template bytes")
    response = _post(client, 
        "/api/templates/create",
        headers={"X-Session-ID": "label-session-7"},
        json={**_label_payload(), "file_path": str(path)},
    )
    assert response.status_code == 200, response.text
    case = _case(repo, response.json()["run_id"])
    assert _verify(case)["status"] == "verified"
    if changed in {"row", "tenant"}:
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE templates SET "
                    + ("template_name='other'" if changed == "row" else "tenant_id=22")
                    + " WHERE id=:id"
                ),
                {"id": response.json()["template"]["db_id"]},
            )
        expected = "result_template_state_mismatch"
    elif changed in {"binding", "database_receipt"}:
        with engine.begin() as db:
            if changed == "database_receipt":
                db.execute(
                    text(
                        "DELETE FROM task_lifecycle_records WHERE module='document_template_mutation' AND task_id=:key"
                    ),
                    {"key": case.key},
                )
            else:
                raw = db.execute(
                    text(
                        "SELECT body_json FROM task_lifecycle_records WHERE module='document_template_mutation' AND task_id=:key"
                    ),
                    {"key": case.key},
                ).scalar_one()
                body = json.loads(raw)
                body["binding"]["call_id"] = "unrelated-call"
                db.execute(
                    text(
                        "UPDATE task_lifecycle_records SET body_json=:body WHERE module='document_template_mutation' AND task_id=:key"
                    ),
                    {"key": case.key, "body": json.dumps(body)},
                )
        expected = (
            "result_template_receipt_mismatch"
            if changed == "binding"
            else "result_template_receipt_unavailable"
        )
    elif changed == "tool_receipt":
        with sqlite3.connect(tmp_path / "tool-claims.sqlite") as db:
            db.execute("DELETE FROM tool_idempotency WHERE scope_key=?", (case.key,))
        expected = "result_receipt_unavailable"
    elif changed == "bytes":
        path.write_bytes(b"different archived template bytes")
        expected = "result_template_file_mismatch"
    else:
        outside = tmp_path / "other-tenant.xlsx"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        expected = "result_template_file_unavailable"
    report = _verify(case)
    assert report["code"] == expected, report
    assert report["status"] != "verified"
