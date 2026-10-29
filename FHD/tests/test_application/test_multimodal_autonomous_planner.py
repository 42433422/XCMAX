from __future__ import annotations

from unittest.mock import Mock, patch

import pytest


def test_multimodal_runtime_context_auto_plans_ingests_and_queries(
    tmp_path,
    monkeypatch,
) -> None:
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "dataset_vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    reset_dataset_rag_app_service_for_tests()

    try:
        run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run(
            user_id="tenant-a",
            message="Which model should the AI route use?",
            runtime_context={
                "dataset_id": "multimodal-eval",
                "tenant_id": "tenant-a",
                "ocr_result": {
                    "success": True,
                    "text": "OCR evidence: AI routes should use the server platform XCauto model.",
                    "confidence": 0.94,
                    "file_path": "/tmp/route-policy.png",
                    "structured_data": {
                        "policy": "server platform model",
                        "model": "XCauto",
                    },
                },
            },
        )
    finally:
        reset_dataset_rag_app_service_for_tests()

    assert run.status == "completed"
    assert run.intent == "multimodal_artifact_rag"
    assert run.metadata["plan"]["metadata"]["source"] == "multimodal_autonomous_planner"
    assert run.metadata["artifact_count"] == 1
    assert run.metadata["dataset_ingest_count"] == 1
    assert run.metadata["dataset_ids"] == ["multimodal-eval"]

    assert len(run.steps) == 1
    assert run.steps[0].tool_id == "dataset_rag"
    assert run.steps[0].action == "query"
    assert run.steps[0].status == "completed"
    assert run.steps[0].risk == "low"
    assert run.steps[0].idempotent is True

    assert len(run.tool_calls) == 1
    tool_call = run.tool_calls[0]
    assert tool_call.tool_id == "dataset_rag"
    assert tool_call.action == "query"
    assert tool_call.status == "completed"
    assert tool_call.permission == "dataset.read"
    assert tool_call.output["success"] is True
    assert "XCauto" in tool_call.output["answer"]
    assert tool_call.output["chunks"]
    assert tool_call.output["citations"]

    event_types = [event.event_type for event in run.events]
    assert "planner.completed" in event_types
    assert "artifact.attached" in event_types
    assert "dataset.ingested" in event_types
    assert "tool.completed" in event_types
    assert "run.completed" in event_types


def test_multimodal_excel_artifact_auto_plans_import_after_approval(
    tmp_path, monkeypatch, local_tools
) -> None:
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "dataset_vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    reset_dataset_rag_app_service_for_tests()

    repo = InMemoryAgentRunRepository()
    try:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run(
            user_id="tenant-a",
            message="把这个 Excel 加入数据库",
            runtime_context={
                "dataset_id": "excel-import-eval",
                "tenant_id": "tenant-a",
                "excel_analysis": {
                    "summary": "Excel 产品清单",
                    "fields": [
                        {"label": "客户"},
                        {"label": "产品名称"},
                        {"label": "型号"},
                        {"label": "单价"},
                    ],
                    "preview_data": {
                        "filename": "products.xlsx",
                        "grid_preview": {
                            "rows": [
                                ["客户", "产品名称", "型号", "单价"],
                                ["甲公司", "清漆", "5003", "120"],
                            ]
                        },
                    },
                },
            },
        )

        assert waiting.status == "waiting_user"
        assert waiting.intent == "multimodal_excel_import_to_db"
        assert waiting.steps[0].tool_id == "excel_import"
        assert waiting.steps[0].action == "import_records"
        assert waiting.steps[0].status == "waiting_user"
        assert waiting.steps[0].risk == "medium"
        assert waiting.steps[0].idempotent is False
        assert waiting.steps[0].params["records"] == [
            {
                "unit_name": "甲公司",
                "product_name": "清漆",
                "model_number": "5003",
                "unit_price": 120.0,
            }
        ]
        assert waiting.metadata["artifact_count"] == 1
        assert waiting.metadata.get("dataset_ingest_count", 0) == 0
        assert not (tmp_path / "dataset_store.json").exists()
        assert not (tmp_path / "dataset_vectors.sqlite3").exists()
        assert waiting.metadata["plan"]["metadata"]["excel_import_record_count"] == 1

        products_service = Mock()
        products_service.get_products.return_value = {"success": True, "data": []}
        products_service.create_product.return_value = {"success": True}
        customer_service = Mock()
        customer_service.match_purchase_unit.return_value = None
        customer_service.create.return_value = {"success": True}

        with (
            patch("app.bootstrap.get_products_service", return_value=products_service),
            patch("app.bootstrap.get_customer_app_service", return_value=customer_service),
        ):
            completed = orchestrator.continue_run(waiting.run_id, approved_by="tester")
    finally:
        reset_dataset_rag_app_service_for_tests()

    assert completed is not None
    assert completed.status == "completed"
    output = completed.final_output["node_outputs"]["import_excel_records"]
    assert output["success"] is True
    assert output["imported_count"] == 1
    assert output["data"]["result"]["created_products"] == 1
    assert completed.tool_calls[0].tool_id == "excel_import"
    assert completed.tool_calls[0].action == "import_records"
    assert completed.tool_calls[0].status == "completed"

    event_types = [event.event_type for event in completed.events]
    assert "planner.completed" in event_types
    assert "artifact.attached" in event_types
    assert "dataset.ingested" in event_types
    assert "step.waiting_user" in event_types
    assert "step.approved" in event_types
    assert "tool.completed" in event_types
    assert "run.completed" in event_types


def test_multimodal_pdf_artifact_auto_plans_document_export_after_approval(
    tmp_path, monkeypatch, local_tools
) -> None:
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "dataset_vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    reset_dataset_rag_app_service_for_tests()

    repo = InMemoryAgentRunRepository()
    try:
        orchestrator = AgentOrchestrator(repository=repo)
        waiting = orchestrator.start_run(
            user_id="tenant-a",
            message="根据这个 PDF 生成一份 Word 风险摘要报告",
            runtime_context={
                "dataset_id": "pdf-export-eval",
                "tenant_id": "tenant-a",
                "multimodal_attachments": [
                    {
                        "name": "risk-policy.pdf",
                        "file_path": "/tmp/risk-policy.pdf",
                        "mime_type": "application/pdf",
                        "text": "PDF evidence: refund approvals require human review and tenant scoped citations.",
                        "summary": "Risk policy PDF",
                    }
                ],
            },
        )

        assert waiting.status == "waiting_user"
        assert waiting.intent == "multimodal_document_export"
        assert waiting.steps[0].tool_id == "generate_office_document"
        assert waiting.steps[0].action == "execute"
        assert waiting.steps[0].status == "waiting_user"
        assert waiting.steps[0].risk == "medium"
        assert waiting.steps[0].idempotent is False
        assert waiting.steps[0].params["output_format"] == "docx"
        assert "risk-policy.pdf" in waiting.steps[0].params["user_request"]
        assert "human review" in waiting.steps[0].params["user_request"]
        assert waiting.metadata["artifact_count"] == 1
        assert waiting.metadata.get("dataset_ingest_count", 0) == 0
        assert not (tmp_path / "dataset_store.json").exists()
        assert not (tmp_path / "dataset_vectors.sqlite3").exists()
        assert (
            waiting.metadata["plan"]["metadata"]["document_export"]["requires_user_confirmation"]
            is True
        )

        with (
            patch(
                "app.domain.shared_services.kitten_ai_document.generate.generate_office_file",
                return_value=(b"content", "risk-summary.docx"),
            ),
            patch(
                "app.domain.shared_services.kitten_ai_document.pickup.store_document_pickup",
                return_value="doc-token",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
            ),
        ):
            completed = orchestrator.continue_run(waiting.run_id, approved_by="tester")
    finally:
        reset_dataset_rag_app_service_for_tests()

    assert completed is not None
    assert completed.status == "completed"
    assert completed.metadata["artifact_count"] == 2
    assert completed.metadata["dataset_ingest_count"] == 2
    assert completed.tool_calls[0].tool_id == "generate_office_document"
    assert completed.tool_calls[0].action == "execute"
    assert completed.tool_calls[0].status == "completed"
    assert completed.tool_calls[0].permission == "tool.generate_office_document.execute"
    assert completed.tool_calls[0].cost_units == 2
    generated = completed.artifacts[-1]
    assert generated.artifact_type == "office_document"
    assert generated.name == "risk-summary.docx"
    assert generated.uri == "/api/ai/kitten/document/pickup/doc-token"

    event_types = [event.event_type for event in completed.events]
    assert "planner.completed" in event_types
    assert "artifact.attached" in event_types
    assert "dataset.ingested" in event_types
    assert "step.waiting_user" in event_types
    assert "step.approved" in event_types
    assert "tool.completed" in event_types
    assert "run.completed" in event_types


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
def test_plan_sources_require_all_write_steps_approved_and_successful(
    tmp_path, monkeypatch, local_tools, outcome
):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import (
        get_dataset_rag_app_service,
        reset_dataset_rag_app_service_for_tests,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    store = tmp_path / "dataset_store.json"
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(store))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    reset_dataset_rag_app_service_for_tests()
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id="review-both-imports",
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
        metadata={"artifacts": [{"artifact_type": "excel_records", "fields": [{"name": "产品"}]}]},
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
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=[{"success": True}, second_result],
        ) as execute:
            waiting = orchestrator.start_run_from_plan(
                user_id="reviewer",
                message="审核并导入两个来源",
                plan=plan,
                runtime_context={"dataset_id": "approved-sources", "tenant_id": "reviewer"},
            )
            assert waiting.status == "waiting_user"
            execute.assert_not_called()
            assert not store.exists()
            second_wait = orchestrator.continue_run(waiting.run_id, approved_by="reviewer")
            assert second_wait.status == "waiting_user"
            assert execute.call_count == 1
            assert not store.exists()
            assert not (tmp_path / "vectors.sqlite3").exists()
            if outcome == "missing_approval":
                # Persisted audit events are immutable; inspect an incomplete detached
                # snapshot at the knowledge materialization boundary instead.
                with patch.object(orchestrator, "_ingest_confirmed_plan_artifacts"):
                    final = orchestrator.continue_run(waiting.run_id, approved_by="reviewer")
                final.events = [
                    event
                    for event in final.events
                    if event.event_type != "step.approved"
                    or event.data.get("step_id") != final.steps[0].step_id
                ]
                orchestrator._ingest_confirmed_plan_artifacts(final)
            else:
                final = orchestrator.continue_run(waiting.run_id, approved_by="reviewer")
            assert execute.call_count == 2

        if outcome != "completed":
            assert final.status == {"failed": "failed", "unknown": "blocked"}.get(
                outcome, "completed"
            )
            assert not store.exists()
            assert final.metadata.get("dataset_ingest_count", 0) == 0
            assert final.artifacts[0].metadata["dataset_ingest_pending_step_ids"]
            return

        assert final.status == "completed"
        assert final.metadata["dataset_ingest_count"] == 1
        reset_dataset_rag_app_service_for_tests()
        stored = get_dataset_rag_app_service().status(dataset_id="approved-sources")
        assert stored["document_count"] == 1
        document = stored["documents"][0]
        assert document["metadata"]["approved_step_ids"] == [step.step_id for step in final.steps]
        # An interrupted optional bridge can replay the same source without a new version.
        final.artifacts[0].metadata.pop("dataset_ingest")
        final.artifacts[0].metadata["dataset_ingest_pending_step_ids"] = [
            step.step_id for step in final.steps
        ]
        orchestrator._ingest_confirmed_plan_artifacts(final)
        replayed = get_dataset_rag_app_service().status(dataset_id="approved-sources")
        assert replayed["document_count"] == 1
        assert replayed["documents"][0]["version"] == document["version"]
    finally:
        reset_dataset_rag_app_service_for_tests()
