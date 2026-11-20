from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import employee_autonomy_service
from modstore_server.admin_employee_autonomy_api import router
from modstore_server.api.deps import require_admin
from modstore_server.duty_workforce_contracts import load_reviewed_duty_manifest
from modstore_server.employee_evolution_dispatch import CuratorCandidateDenied, _candidate_archive
from modstore_server.employee_runtime import parse_employee_config_v2
from modstore_server.integrations.repository_packages import load_repository_module
from modstore_server.models import (
    CatalogItem,
    EmployeeEvolutionRecord,
    EmployeeExecutionMetric,
    EmployeeSuggestion,
    User,
    get_session_factory,
    init_db,
)


def test_candidate_rejects_changes_to_structured_prompt_prefix(tmp_path):
    manifest = load_reviewed_duty_manifest("doc-knowledge-curator")
    manifest["employee_config_v2"]["cognition"]["agent"]["role"] = {"name": "知识策展员"}
    before = parse_employee_config_v2(manifest)["cognition"]["agent"]["system_prompt"].strip()
    source = tmp_path / "employee.xcemp"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("doc-knowledge-curator/manifest.json", json.dumps(manifest))
    record = EmployeeEvolutionRecord(
        employee_id="doc-knowledge-curator", prompt_before=before, prompt_after="不同的角色约束"
    )
    with pytest.raises(CuratorCandidateDenied, match="employee_pack_structured_prompt_changed"):
        _candidate_archive(source, hashlib.sha256(source.read_bytes()).hexdigest(), record)


@pytest.mark.parametrize("legacy_dispatched", [False, True])
@pytest.mark.parametrize("structured", [False, True, "legacy"])
def test_operator_approval_executes_real_curator_and_reads_private_candidate(
    tmp_path, monkeypatch, legacy_dispatched, structured
):
    repo = Path(__file__).resolve().parents[3]
    catalog = tmp_path / "catalog"
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(repo))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "curator.db"))
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("RETORT_ARTIFACT_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    events = []
    reports = []
    monkeypatch.setattr(
        employee_autonomy_service, "_publish_event", lambda *args, **kwargs: events.append(args[0])
    )
    monkeypatch.setattr(
        "modstore_server.employee_collab_reporter.report_suggestion_dispatched",
        lambda **kwargs: reports.append(kwargs["suggestion_id"]),
    )
    init_db()
    employee_id = "doc-knowledge-curator"
    manifest = load_reviewed_duty_manifest(employee_id)
    agent = manifest["employee_config_v2"]["cognition"]["agent"]
    if structured == "legacy":
        cognition = manifest["employee_config_v2"]["cognition"]
        cognition["system_prompt"] = agent["system_prompt"]
        del cognition["agent"]
    elif structured:
        agent["role"] = {"name": "知识策展员"}
        agent["behavior_rules"] = ["核对来源"]
        agent["few_shot_examples"] = [{"input": "问题", "output": "引用"}]
    before = parse_employee_config_v2(manifest)["cognition"]["agent"]["system_prompt"].strip()
    after = before + "\n核对知识条目的引用出处。"
    artifact = catalog / "files" / "existing.xcemp"
    artifact.parent.mkdir(parents=True)
    with zipfile.ZipFile(artifact, "w") as source:
        source.writestr(f"{employee_id}/manifest.json", json.dumps(manifest))
        source.writestr(f"{employee_id}/backend/employees/worker.py", b"# retained runtime")
        source.writestr("META-INF/signature.json", b"signature for the original manifest")
    original = artifact.read_bytes()
    with get_session_factory()() as db:
        admin = User(username="evolution-admin", password_hash="test", is_admin=True)
        suggestion = EmployeeSuggestion(
            source_employee_id="evolution-engine",
            target_employee_ids_json='["employee-pack-curator"]',
            kind="employee_evolution",
            payload_json=json.dumps(
                {"employee_id": employee_id, "prompt_before": before, "prompt_after": after}
            ),
            risk_level="medium",
        )
        db.add_all(
            [
                admin,
                suggestion,
                CatalogItem(
                    pkg_id=employee_id,
                    version=manifest["version"],
                    name=manifest["name"],
                    artifact="employee_pack",
                    stored_filename=artifact.name,
                    sha256=hashlib.sha256(original).hexdigest(),
                    is_public=True,
                ),
            ]
        )
        db.flush()
        suggestion_id, admin_id = suggestion.id, admin.id
        db.add(
            EmployeeEvolutionRecord(
                employee_id=employee_id,
                created_suggestion_id=suggestion_id,
                prompt_before=before,
                prompt_after=after,
            )
        )
        db.commit()
    assert employee_autonomy_service.dispatch_suggestion(
        suggestion_id, force_approve_if_needed=True
    ) == {
        "ok": False,
        "error": "curator_approval_required",
    }
    if legacy_dispatched:
        with get_session_factory()() as db:
            row = db.get(EmployeeSuggestion, suggestion_id)
            row.approved_by_user_id = admin_id
            row.approved_at = datetime.now(UTC)
            row.status = "dispatched"
            row.created_task_ids_json = '["employee-pack-curator"]'
            db.commit()
        assert employee_autonomy_service.dispatch_pending_suggestions()["ok_count"] == 1
        assert employee_autonomy_service.dispatch_pending_suggestions()["processed"] == 0
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: User(id=admin_id, is_admin=True)
    with TestClient(app) as client:
        route = f"/api/admin/employee-autonomy/suggestions/{suggestion_id}/approve"
        response = client.post(route, json={"dispatch_now": True})
        assert response.status_code == 200, response.json()
        receipt = response.json()
        assert client.post(route, json={"dispatch_now": True}).json() == receipt

    assert receipt["signature_status"] == "awaiting_release_signature"
    assert events.count("employee.suggestion.dispatched") == 1
    assert reports == [suggestion_id]
    assert artifact.read_bytes() == original
    private = load_repository_module("retort_engine.secure_artifacts")
    evidence = private.read_private_json(runtime / receipt["artifact_ref"], allow_legacy=False)
    candidate = base64.b64decode(evidence["files"]["candidate.xcemp"])
    assert hashlib.sha256(candidate).hexdigest() == receipt["candidate_sha256"]
    with zipfile.ZipFile(io.BytesIO(candidate)) as staged:
        actual_manifest = json.loads(staged.read(f"{employee_id}/manifest.json"))
        assert (
            parse_employee_config_v2(actual_manifest)["cognition"]["agent"]["system_prompt"]
            == after
        )
        if structured is True:
            assert (
                actual_manifest["employee_config_v2"]["cognition"]["agent"]["role"] == agent["role"]
            )
        assert staged.read(f"{employee_id}/backend/employees/worker.py") == b"# retained runtime"
        assert "META-INF/signature.json" not in staged.namelist()
    audit = json.loads(base64.b64decode(evidence["files"]["receipt.json"]))["audit"]
    assert audit["meta"]["employee_id"] == "employee-pack-curator"
    assert audit["ready_for_packaging"] is True
    with get_session_factory()() as db:
        row = db.get(EmployeeSuggestion, suggestion_id)
        assert row.status == "done"
        assert row.created_task_ids_json == json.dumps([receipt["metric_id"]])
        metric = db.get(EmployeeExecutionMetric, receipt["metric_id"])
        assert metric.status == "success"
        assert metric.task == f"employee-evolution:{suggestion_id}"
        assert db.query(EmployeeExecutionMetric).count() == 1
    (runtime / receipt["artifact_ref"]).unlink()
    assert employee_autonomy_service.approve_suggestion(
        suggestion_id, approved_by_user_id=admin_id
    ) == {"ok": False, "error": "curator_receipt_unverified"}
    with get_session_factory()() as db:
        assert db.query(EmployeeExecutionMetric).count() == 1
