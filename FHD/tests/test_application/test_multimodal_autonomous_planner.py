from __future__ import annotations

from unittest.mock import Mock, patch


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
        assert waiting.metadata["dataset_ingest_count"] == 1
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
        assert waiting.metadata["dataset_ingest_count"] == 1
        assert waiting.metadata["plan"]["metadata"]["document_export"]["requires_user_confirmation"] is True

        with (
            patch(
                "app.services.kitten_ai_document.generate.generate_office_file",
                return_value=(b"content", "risk-summary.docx"),
            ),
            patch(
                "app.services.kitten_ai_document.pickup.store_document_pickup",
                return_value="doc-token",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool", return_value=(None, None)),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool", return_value=None),
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
