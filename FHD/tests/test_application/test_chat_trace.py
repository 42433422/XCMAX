from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.infrastructure.billing import model_usage


@pytest.fixture(autouse=True)
def _isolated_agent_usage_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_BACKEND", raising=False)
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def test_attach_chat_trace_run_persists_completed_run() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {"success": True, "response": "done", "data": {"text": "done"}}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="查库存",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run_id = result["run_id"]
    assert result["data"]["run_id"] == run_id

    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "u1"
    assert run.status == "completed"
    assert run.intent == "chat_reply"
    assert run.metadata["source"] == "desktop"
    assert run.metadata["channel"] == "compat_chat"
    assert run.final_output["chat_payload"]["response"] == "done"
    assert [event.event_type for event in run.events] == ["run.created", "run.completed"]


def test_attach_chat_trace_run_accepts_explicit_intent() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {"success": True, "response": "done", "data": {"text": "done"}}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="导入数据库",
            runtime_context={"workflow_trace_mode": "deterministic_shortcut"},
            user_id="u1",
            source="pro",
            channel="deterministic_workflow",
            intent="excel_import_to_db",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.intent == "excel_import_to_db"
    assert run.metadata["channel"] == "deterministic_workflow"
    assert run.metadata["runtime_context"]["workflow_trace_mode"] == "deterministic_shortcut"


def test_attach_chat_trace_run_records_llm_calls(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    trace = {
        "provider_id": "openai_compatible",
        "provider": "xcauto",
        "model": "xcauto-account",
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "latency_ms": 12.5,
        "cost_units": 1,
        "billing_status": "metered",
        "billing_source": "estimated_token_units",
    }
    payload = {
        "success": True,
        "response": "done",
        "data": {"text": "done", "llm_trace": trace},
        "_xcagi_trace": trace,
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="普通问答",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert len(run.llm_calls) == 1
    assert run.llm_calls[0].provider == "xcauto"
    assert run.llm_calls[0].model == "xcauto-account"
    assert run.llm_calls[0].total_tokens == 5
    assert run.llm_calls[0].cost_units == 1
    assert run.llm_calls[0].billing_status == "metered"
    assert run.llm_calls[0].metadata["usage_ledger"]["status"] == "recorded"
    assert run.metadata["llm_call_count"] == 1
    assert run.metadata["llm_token_total"] == 5
    assert run.metadata["llm_cost_units_total"] == 1
    assert run.metadata["ai_cost_units_total"] == 1
    assert run.metadata["model_usage_entry_count"] == 1
    assert run.metadata["model_usage_cost_units_total"] == 1
    assert run.metadata["model_usage_ledger_status"] == "recorded"
    assert run.final_output["llm_calls"][0]["provider"] == "xcauto"
    assert run.final_output["llm_calls"][0]["metadata"]["usage_ledger"]["status"] == "recorded"
    assert run.final_output["llm_cost_units_total"] == 1
    assert run.final_output["ai_cost_units_total"] == 1
    assert [event.event_type for event in run.events] == [
        "run.created",
        "llm.completed",
        "billing.recorded",
        "run.completed",
    ]
    assert model_usage.model_usage_database_path().is_file()
    ledger = model_usage._load_usage_state()
    assert ledger["summary"]["entry_count"] == 1
    assert ledger["summary"]["cost_units_total"] == 1
    assert ledger["entries"][0]["run_id"] == run.run_id
    assert ledger["entries"][0]["provider"] == "xcauto"
    assert ledger["entries"][0]["model"] == "xcauto-account"


def test_attach_chat_trace_run_debits_local_model_wallet(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    from app.infrastructure.billing.model_usage import get_model_wallet, set_model_wallet_balance

    set_model_wallet_balance("u1", 2, reason="test")
    trace = {
        "provider_id": "openai_compatible",
        "provider": "xcauto",
        "model": "xcauto-account",
        "total_tokens": 5,
        "cost_units": 1,
        "billing_status": "metered",
        "billing_source": "estimated_token_units",
    }
    payload = {"success": True, "response": "done", "data": {"llm_trace": trace}}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="普通问答",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.llm_calls[0].billing_status == "debited"
    assert run.llm_calls[0].billing_source == "local_model_wallet"
    assert run.llm_calls[0].metadata["wallet_debit"]["balance_after_units"] == 1
    assert run.metadata["model_wallet_balance_units"] == 1
    assert "billing.debited" in [event.event_type for event in run.events]
    assert get_model_wallet("u1")["balance_units"] == 1


def test_attach_chat_trace_run_fails_when_model_wallet_insufficient(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    trace = {
        "provider_id": "openai_compatible",
        "provider": "xcauto",
        "model": "xcauto-account",
        "total_tokens": 5,
        "cost_units": 1,
        "billing_status": "metered",
        "billing_source": "estimated_token_units",
    }
    payload = {"success": True, "response": "done", "data": {"llm_trace": trace}}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="普通问答",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "failed"
    assert run.error == "AI wallet balance insufficient"
    assert run.llm_calls[0].billing_status == "insufficient_balance"
    assert run.llm_calls[0].metadata["wallet_debit"]["shortfall_units"] == 1
    assert "billing.insufficient_balance" in [event.event_type for event in run.events]


def test_attach_chat_trace_run_records_rag_retrieval() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "付款条款是 30 天",
        "data": {
            "text": "付款条款是 30 天",
            "query": "合同付款条款",
            "rag_enabled": True,
            "dataset_id": "contracts",
            "chunks": [
                {
                    "chunk_index": 0,
                    "text": "付款条款：验收后 30 天内付款",
                    "score": 0.91,
                    "source": "contract.pdf",
                }
            ],
            "citations": [
                {
                    "index": 1,
                    "text": "付款条款：验收后 30 天内付款",
                    "source": "contract.pdf",
                    "chunk_index": 0,
                }
            ],
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="合同付款条款是什么",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert len(run.retrieval_calls) == 1
    assert run.retrieval_calls[0].query == "合同付款条款"
    assert run.retrieval_calls[0].source == "contracts"
    assert run.retrieval_calls[0].chunks[0]["source"] == "contract.pdf"
    assert run.retrieval_calls[0].citations[0]["source"] == "contract.pdf"
    assert run.metadata["retrieval_call_count"] == 1
    assert run.metadata["retrieval_chunk_count"] == 1
    assert run.metadata["citation_count"] == 1
    assert run.final_output["retrieval_calls"][0]["citations"][0]["source"] == "contract.pdf"
    assert [event.event_type for event in run.events] == [
        "run.created",
        "rag.retrieved",
        "run.completed",
    ]


def test_attach_chat_trace_run_records_user_memory_reference() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "按上次客户偏好优先看涂料类",
        "data": {
            "text": "按上次客户偏好优先看涂料类",
            "query": "上次客户偏好是什么",
            "user_memory_rag_summary": "【UserMemoryRAG】召回 1 条：客户偏好先看涂料类报价",
            "user_memory_hits": [
                {
                    "chunk_id": "mem1",
                    "content": "客户偏好先看涂料类报价",
                    "score": 0.88,
                    "metadata": {"intent": "business_db_read"},
                }
            ],
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="按上次客户偏好查询",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert len(run.memory_references) == 1
    assert run.memory_references[0].query == "上次客户偏好是什么"
    assert run.memory_references[0].source == "user_memory_rag"
    assert run.memory_references[0].hits[0]["chunk_id"] == "mem1"
    assert run.memory_references[0].summary.startswith("【UserMemoryRAG】")
    assert run.metadata["memory_reference_count"] == 1
    assert run.metadata["memory_hit_count"] == 1
    assert run.metadata["memory_sources"] == ["user_memory_rag"]
    assert run.final_output["memory_references"][0]["hits"][0]["chunk_id"] == "mem1"
    assert run.final_output["memory_hit_count"] == 1
    assert [event.event_type for event in run.events] == [
        "run.created",
        "memory.recalled",
        "run.completed",
    ]


def test_attach_chat_trace_run_records_ocr_artifact(tmp_path, monkeypatch) -> None:
    from app.application.dataset_rag_app_service import (
        reset_dataset_rag_app_service_for_tests,
    )

    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    reset_dataset_rag_app_service_for_tests()
    service = Mock()
    service.ingest_document.side_effect = AssertionError("trace is display-only")
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "识别到购货单位",
        "data": {
            "text": "识别到购货单位",
            "ocr_result": {
                "success": True,
                "text": "购货单位：星光贸易\n联系人：张三",
                "confidence": 0.93,
                "file_path": "/tmp/label.png",
                "structured_data": {
                    "purchase_unit": "星光贸易",
                    "contact_person": "张三",
                },
            },
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="识别这张产品图",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert len(run.artifacts) == 1
    assert run.artifacts[0].artifact_type == "ocr_text"
    assert run.artifacts[0].uri == "/tmp/label.png"
    assert run.artifacts[0].fields[0]["name"] == "purchase_unit"
    assert run.artifacts[0].preview["confidence"] == 0.93
    assert run.metadata["artifact_count"] == 1
    assert run.metadata["artifact_types"] == ["ocr_text"]
    assert run.artifacts[0].metadata["skip_dataset_ingest"] is True
    assert run.final_output["artifacts"][0]["artifact_type"] == "ocr_text"
    assert not run.metadata.get("dataset_ingest_count")
    service.ingest_document.assert_not_called()
    assert [event.event_type for event in run.events] == [
        "run.created",
        "artifact.attached",
        "run.completed",
    ]
    reset_dataset_rag_app_service_for_tests()


def test_attach_chat_trace_run_displays_pdf_without_implicit_ingestion(
    tmp_path, monkeypatch
) -> None:
    from app.application.dataset_rag_app_service import (
        reset_dataset_rag_app_service_for_tests,
    )
    from evals.run_agent_eval import _minimal_pdf_bytes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    reset_dataset_rag_app_service_for_tests()
    service = Mock()
    service.ingest_document.side_effect = AssertionError("trace is display-only")
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    repo = InMemoryAgentRunRepository()
    pdf_path = tmp_path / "xcauto_policy.pdf"
    pdf_path.write_bytes(
        _minimal_pdf_bytes(
            "All AI routes should use the server platform XCauto model. "
            "Artifacts from PDF analysis must enter Dataset RAG with citations."
        )
    )
    payload = {
        "success": True,
        "response": "PDF 已解析",
        "data": {
            "text": "PDF 已解析",
            "file_analysis": {
                "success": True,
                "parser_used": "pdfplumber",
                "extension": ".pdf",
                "file_path": str(pdf_path),
                "saved_name": "xcauto_policy.pdf",
                "text_preview": "All AI routes should use the server platform XCauto model.",
                "ai_summary": "XCauto policy PDF",
            },
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="解析并加入知识库",
            runtime_context={"workspace": "demo", "dataset_id": "platform-docs"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.artifacts[0].artifact_type == "pdf_document"
    assert run.artifacts[0].metadata["skip_dataset_ingest"] is True
    assert run.artifacts[0].metadata["parser_used"] == "pdfplumber"
    assert not run.metadata.get("dataset_ingest_count")
    assert "dataset.ingested" not in [event.event_type for event in run.events]
    service.ingest_document.assert_not_called()
    assert not (tmp_path / "dataset_store.json").exists()
    reset_dataset_rag_app_service_for_tests()


def test_attach_chat_trace_run_displays_office_without_implicit_ingestion(
    tmp_path, monkeypatch
) -> None:
    from docx import Document

    from app.application.dataset_rag_app_service import (
        reset_dataset_rag_app_service_for_tests,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset_store.json"))
    reset_dataset_rag_app_service_for_tests()
    service = Mock()
    service.ingest_document.side_effect = AssertionError("trace is display-only")
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    repo = InMemoryAgentRunRepository()
    docx_path = tmp_path / "platform_notes.docx"
    doc = Document()
    doc.add_paragraph("Office artifacts should enter Dataset RAG automatically.")
    doc.add_paragraph("The server platform model is XCauto.")
    doc.save(str(docx_path))
    payload = {
        "success": True,
        "response": "DOCX 已解析",
        "data": {
            "text": "DOCX 已解析",
            "file_analysis": {
                "success": True,
                "parser_used": "python-docx",
                "extension": ".docx",
                "file_path": str(docx_path),
                "saved_name": "platform_notes.docx",
                "text_preview": "The server platform model is XCauto.",
                "ai_summary": "Platform notes DOCX",
            },
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="解析 Office 并加入知识库",
            runtime_context={"workspace": "demo", "dataset_id": "office-docs"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.artifacts[0].artifact_type == "office_document"
    assert run.artifacts[0].metadata["skip_dataset_ingest"] is True
    assert run.artifacts[0].metadata["parser_used"] == "python-docx"
    assert not run.metadata.get("dataset_ingest_count")
    service.ingest_document.assert_not_called()
    assert not (tmp_path / "dataset_store.json").exists()
    reset_dataset_rag_app_service_for_tests()


def test_attach_chat_trace_run_records_generated_office_artifact() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "合同已生成",
        "data": {
            "text": "合同已生成",
            "file_name": "contract.docx",
            "download_url": "/api/ai/kitten/document/pickup/doc-token",
            "pickup_token": "doc-token",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message="生成合同",
            runtime_context={"workspace": "demo"},
            user_id="u1",
            source="desktop",
            channel="compat_chat",
        )

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert len(run.artifacts) == 1
    assert run.artifacts[0].artifact_type == "office_document"
    assert run.artifacts[0].name == "contract.docx"
    assert run.artifacts[0].uri == "/api/ai/kitten/document/pickup/doc-token"
    assert run.artifacts[0].preview["pickup_token"] == "doc-token"
    assert run.metadata["artifact_types"] == ["office_document"]
    assert run.final_output["artifacts"][0]["artifact_type"] == "office_document"
    assert [event.event_type for event in run.events] == [
        "run.created",
        "artifact.attached",
        "run.completed",
    ]


def test_attach_chat_trace_run_preserves_authorization_wait() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "requires_token": True,
        "token_name": "DB_READ_TOKEN",
        "message": "需要授权",
        "data": {"requires_token": True},
    }
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(payload, message="读取业务数据", runtime_context={})

    run = repo.get(result["run_id"])
    assert run is not None and run.status == "waiting_user"
    assert run.events[-1].event_type == "step.waiting_user"


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "data": {"action": "tool_call", "tool_key": "products"}},
        {
            "success": True,
            "toolCall": {"tool_id": "products", "action": "query", "params": {"keyword": "5003"}},
        },
        {
            "success": True,
            "data": {"legacy_tool_records": [{"tool_id": "products", "output": {"success": True}}]},
        },
    ],
)
def test_attach_chat_trace_run_rejects_unplanned_tool_payloads(payload) -> None:
    repo = InMemoryAgentRunRepository()
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(payload, message="查产品", runtime_context={}, user_id="u1")

    assert result["success"] is False
    assert result["execution_state"] == "failed"
    assert result["data"]["action"] == "unplanned_tool_call_rejected"
    assert result["data"]["execution_started"] is False
    run = repo.get(result["run_id"])
    assert run is not None and run.status == "failed" and run.tool_calls == []
    assert "未经计划校验" in result["response"]
    assert run.final_output["chat_payload"]["success"] is False
    assert "toolCall" not in result
    assert "legacy_tool_records" not in result["data"]
    assert "tool_key" not in result["data"]
    assert payload["success"] is True  # The caller's model output is not mutated.


def test_attach_chat_trace_run_skips_existing_run_id() -> None:
    repo = InMemoryAgentRunRepository()
    payload = {"success": True, "run_id": "run_existing", "data": {"text": "ok"}}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(payload, message="hello", runtime_context={})

    assert result["run_id"] == "run_existing"
    assert repo.list_recent() == []
