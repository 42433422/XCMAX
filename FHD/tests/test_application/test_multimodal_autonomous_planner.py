"""Multimodal planning uses owned uploads and signed actors, never client paths."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request


@pytest.fixture
def signed_actor(tmp_path):
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from evals.run_agent_eval import _authenticated_route_fixture, _isolated_task_execution_queue

    client = SimpleNamespace(headers={})
    with (
        _authenticated_route_fixture(client, role_name="admin"),
        _isolated_task_execution_queue(tmp_path),
    ):
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        yield (
            principal,
            authenticated_runtime_context({"dataset_id": "approved-sources"}, principal),
        )


@pytest.mark.parametrize(
    "task_id",
    [
        "multimodal_ocr_artifact_autonomous_plan",
        "multimodal_excel_artifact_autonomous_import_plan",
        "multimodal_pdf_artifact_autonomous_document_export_plan",
        "owned_pdf_explicit_knowledge_import",
    ],
)
def test_owned_multimodal_planning_preserves_effects_and_approval(tmp_path, task_id):
    from evals.run_agent_eval import load_tasks, run_eval

    task = next(task for task in load_tasks() if task["id"] == task_id)
    tasks = tmp_path / "attachment-contract.jsonl"
    tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    result = run_eval(tasks)["results"][0]
    assert result["passed"], result["failed_checks"]
    run = result["details"]["run"]
    source = run["artifacts"][0]
    assert source["source"] == "plan.metadata"
    assert source["metadata"]["parser_used"] == "owned_upload"
    assert source["metadata"]["upload_id"]
    assert source["metadata"]["skip_dataset_ingest"] is True
    assert source["uri"] == ""
    if task["attachment_kind"] == "excel":
        output = run["final_output"]["node_outputs"]["import_excel_records"]
        assert output["success"] is True
        assert output["imported_count"] == 1
        assert output["data"]["result"]["created_products"] == 1
    elif task.get("mock_office_document"):
        artifact = run["artifacts"][-1]
        assert artifact["artifact_type"] == "office_document"
        assert artifact["name"] == "risk-summary.docx"
        assert artifact["uri"] == "/api/ai/kitten/document/pickup/eval-doc-token"
    elif not task.get("explicit_knowledge_import"):
        assert not run["tool_calls"]
        assert run["metadata"].get("dataset_ingest_count", 0) == 0


@pytest.mark.parametrize(
    "outcome",
    [
        "completed",
        "failed",
        "unknown",
        "outcome_unknown",
        "requires_reconciliation",
        "missing_approval",
    ],
)
def test_plan_sources_never_gain_knowledge_authority_from_business_approval(
    tmp_path, monkeypatch, local_tools, signed_actor, outcome
):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import (
        get_dataset_rag_app_service,
        reset_dataset_rag_app_service_for_tests,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    principal, context = signed_actor
    store = tmp_path / "dataset_store.json"
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(store))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    reset_dataset_rag_app_service_for_tests()
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id=f"review-both-imports-{outcome}-{tmp_path.name}",
        intent="excel_import_to_db",
        nodes=[
            WorkflowNode(
                node_id=f"import_{number}",
                tool_id="excel_import",
                action="import_records",
                params={"records": [{"product_name": f"样例-{number}"}]},
                risk="medium",
                idempotent=False,
            )
            for number in (1, 2)
        ],
        metadata={
            "artifacts": [
                {
                    "artifact_type": "excel_records",
                    "source": "tool.output",
                    "preview": {"text": "Untrusted plan source must not become stored knowledge"},
                    "fields": [{"name": "产品"}],
                    "metadata": {
                        "skip_dataset_ingest": False,
                        "tenant_id": "other-tenant",
                        "dataset_id": "unapproved-dataset",
                    },
                }
            ],
        },
    )
    second_result = {"success": outcome not in {"failed", "unknown"}}
    if outcome == "unknown":
        second_result.update(outcome="unknown", reconciliation_required=True, retryable=False)
    if outcome in {"outcome_unknown", "requires_reconciliation"}:
        second_result[outcome] = True
    if outcome == "failed":
        second_result["artifact"] = {
            "artifact_type": "ocr_text",
            "preview": {"text": "失败工具返回的附件只供审核，不应作为正式知识"},
        }
    try:
        dataset = get_dataset_rag_app_service()
        with (
            patch.object(dataset, "ingest_document", wraps=dataset.ingest_document) as ingest,
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=[{"success": True}, second_result],
            ) as execute,
        ):
            waiting = orchestrator.start_run_from_plan(
                user_id=principal.user_id,
                message="审核并导入两个来源",
                plan=plan,
                runtime_context=context,
            )
            assert waiting.status == "waiting_user"
            execute.assert_not_called()
            assert not store.exists()
            second_wait = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
            assert second_wait.status == "waiting_user"
            assert execute.call_count == 1, second_wait.to_dict()
            assert not store.exists()
            with sqlite3.connect(tmp_path / "vectors.sqlite3") as vector_db:
                assert (
                    vector_db.execute("SELECT COUNT(*) FROM dataset_vector_chunks").fetchone()[0]
                    == 0
                )
            if outcome == "missing_approval":
                # Persisted audit events are immutable; inspect an incomplete detached
                # snapshot at the knowledge materialization boundary instead.
                with patch.object(orchestrator, "_ingest_confirmed_plan_artifacts"):
                    final = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
                final.events = [
                    event
                    for event in final.events
                    if event.event_type != "step.approved"
                    or event.data.get("step_id") != final.steps[0].step_id
                ]
                orchestrator._ingest_confirmed_plan_artifacts(final)
            else:
                final = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
            assert execute.call_count == 2

            assert final.status == {"failed": "failed", "unknown": "blocked"}.get(
                outcome, "completed"
            )
            # Approving business imports authorizes those imports, not knowledge
            # writes or destinations supplied by an untrusted model artifact.
            ingest.assert_not_called()
            assert not store.exists()
            with sqlite3.connect(tmp_path / "vectors.sqlite3") as vector_db:
                assert (
                    vector_db.execute("SELECT COUNT(*) FROM dataset_vector_chunks").fetchone()[0]
                    == 0
                )
            assert final.metadata.get("dataset_ingest_count", 0) == 0
            source = final.artifacts[0]
            assert source.metadata["skip_dataset_ingest"] is True
            assert (
                source.preview["text"] == "Untrusted plan source must not become stored knowledge"
            )
            # Replaying materialization must not turn completed business approvals
            # into authority, even if the artifact spoofs source or destination.
            orchestrator._ingest_confirmed_plan_artifacts(final)
            ingest.assert_not_called()
            assert not store.exists()
    finally:
        reset_dataset_rag_app_service_for_tests()
