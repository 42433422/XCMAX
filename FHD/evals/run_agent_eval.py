from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

FHD_ROOT = Path(__file__).resolve().parents[1]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

DEFAULT_TASKS_PATH = Path(__file__).with_name("agent_tasks.jsonl")

_LLM_ENV_KEYS = (
    "XCAUTO_API_KEY",
    "XCAUTO_PAT",
    "XIUCI_API_KEY",
    "XCAUTO_BASE_URL",
    "XCAUTO_API_BASE",
    "XCAUTO_API_URL",
    "XCAUTO_CHAT_COMPLETIONS_URL",
    "XCAUTO_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL",
    "LLM_PROVIDER",
    "XCAGI_LLM_PROVIDER",
    "LLM_MODEL",
    "DP_MODEL",
)


def load_tasks(path: Path = DEFAULT_TASKS_PATH) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError(f"{path}:{line_number} must be a JSON object")
        data.setdefault("_line_number", line_number)
        tasks.append(data)
    return tasks


def run_eval(path: Path = DEFAULT_TASKS_PATH) -> dict[str, Any]:
    results = [run_task(task) for task in load_tasks(path)]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "suite": "agent_platform_minimum",
        "tasks_path": str(path),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "score": round(passed / total, 4) if total else 0.0,
        "results": results,
    }


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    kind = str(task.get("kind") or "")
    if kind == "agent_plan":
        return _run_agent_plan_task(task)
    if kind == "xcauto_credentials":
        return _run_xcauto_credentials_task(task)
    if kind == "llm_trace":
        return _run_llm_trace_task(task)
    if kind == "agent_run_llm_trace":
        return _run_agent_run_llm_trace_task(task)
    if kind == "agent_run_rag_trace":
        return _run_agent_run_rag_trace_task(task)
    if kind == "agent_run_memory_trace":
        return _run_agent_run_memory_trace_task(task)
    if kind == "memory_v2_lifecycle":
        return _run_memory_v2_lifecycle_task(task)
    if kind == "memory_v2_planner_context":
        return _run_memory_v2_planner_context_task(task)
    if kind == "memory_v2_governance":
        return _run_memory_v2_governance_task(task)
    if kind == "agent_run_artifact_trace":
        return _run_agent_run_artifact_trace_task(task)
    if kind == "multimodal_autonomous_plan":
        return _run_multimodal_autonomous_plan_task(task)
    if kind == "excel_vector_route_agent":
        return _run_excel_vector_route_agent_task(task)
    if kind == "ocr_route_agent":
        return _run_ocr_route_agent_task(task)
    if kind == "business_ocr_route_agent":
        return _run_business_ocr_route_agent_task(task)
    if kind == "business_event_route_agent":
        return _run_business_event_route_agent_task(task)
    if kind == "system_maintenance_route_agent":
        return _run_system_maintenance_route_agent_task(task)
    if kind == "dataset_rag_route_agent":
        return _run_dataset_rag_route_agent_task(task)
    if kind == "memory_v2_route_agent":
        return _run_memory_v2_route_agent_task(task)
    if kind == "materials_route_agent":
        return _run_materials_route_agent_task(task)
    if kind == "inventory_route_agent":
        return _run_inventory_route_agent_task(task)
    if kind == "purchase_route_agent":
        return _run_purchase_route_agent_task(task)
    if kind == "finance_route_agent":
        return _run_finance_route_agent_task(task)
    if kind == "products_route_agent":
        return _run_products_route_agent_task(task)
    if kind == "products_compat_route_agent":
        return _run_products_compat_route_agent_task(task)
    if kind == "customers_route_agent":
        return _run_customers_route_agent_task(task)
    if kind == "shipment_records_route_agent":
        return _run_shipment_records_route_agent_task(task)
    if kind == "shipment_orders_route_agent":
        return _run_shipment_orders_route_agent_task(task)
    if kind == "print_route_agent":
        return _run_print_route_agent_task(task)
    if kind == "tools_execute_route_agent":
        return _run_tools_execute_route_agent_task(task)
    if kind == "templates_analyze_route_agent":
        return _run_templates_analyze_route_agent_task(task)
    if kind == "excel_skill_route_agent":
        return _run_excel_skill_route_agent_task(task)
    if kind == "label_template_route_agent":
        return _run_label_template_route_agent_task(task)
    if kind == "document_template_route_agent":
        return _run_document_template_route_agent_task(task)
    if kind == "dataset_rag_document_qa":
        return _run_dataset_rag_document_qa_task(task)
    if kind == "dataset_rag_governance":
        return _run_dataset_rag_governance_task(task)
    if kind == "dataset_rag_version_ops":
        return _run_dataset_rag_version_ops_task(task)
    if kind == "dataset_rag_rbac":
        return _run_dataset_rag_rbac_task(task)
    if kind == "dataset_rag_rebuild_queue":
        return _run_dataset_rag_rebuild_queue_task(task)
    if kind == "dataset_rag_vector_backend":
        return _run_dataset_rag_vector_backend_task(task)
    return _failed(task, f"unknown task kind: {kind}")


def _run_agent_plan_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository

    checks: list[dict[str, Any]] = []
    expected = dict(task.get("expected") or {})
    dispatches: list[dict[str, Any]] = []
    market_calls: list[dict[str, Any]] = []
    mock_results = [
        dict(item)
        for item in list(task.get("mock_results") or [])
        if isinstance(item, dict)
    ]

    def fake_execute(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch_index = len(dispatches)
        dispatches.append(
            {
                "tool_id": tool_id,
                "action": action,
                "params": _json_safe(params),
            }
        )
        if dispatch_index < len(mock_results):
            return dict(mock_results[dispatch_index])
        return dict(task.get("mock_result") or {"success": True})

    repo = InMemoryAgentRunRepository()
    with tempfile.TemporaryDirectory() as tmp_dir:
        with ExitStack() as stack:
            wallet_backend = str(task.get("wallet_backend") or "audit").strip().lower() or "audit"
            env_patch = {
                "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "model_usage.json"),
                "MODEL_USAGE_WALLET_BACKEND": wallet_backend,
                "MODEL_USAGE_WALLET_REQUIRED": "1" if task.get("wallet_required") else "",
            }
            if wallet_backend == "market":
                env_patch.update(
                    {
                        "MODEL_USAGE_MARKET_BASE_URL": str(
                            task.get("market_base_url") or "http://market.eval"
                        ),
                        "MODEL_USAGE_MARKET_AUTH_TOKEN": str(
                            task.get("market_auth_token") or "eval-market-token"
                        ),
                        "MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT": str(
                            task.get("market_yuan_per_cost_unit") or "0.02"
                        ),
                    }
                )
            if isinstance(task.get("llm_repair_response"), dict):
                env_patch.update(
                    {
                        "LLM_PROVIDER": "xcauto",
                        "XCAUTO_API_KEY": "eval-xcauto-token",
                    }
                )
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            if "wallet_balance_units" in task:
                from app.infrastructure.billing.model_usage import set_model_wallet_balance

                set_model_wallet_balance(
                    "eval-user",
                    int(task.get("wallet_balance_units") or 0),
                    reason="agent_eval",
                )
            if wallet_backend == "market":
                from app.infrastructure.billing import model_usage

                responses = _market_wallet_eval_responses(task)
                stack.enter_context(
                    patch.object(
                        model_usage.httpx,
                        "Client",
                        lambda *args, **kwargs: _EvalMarketWalletClient(responses, market_calls),
                    )
                )
            stack.enter_context(
                patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool",
                    side_effect=fake_execute,
                )
            )
            if isinstance(task.get("llm_repair_response"), dict):
                stack.enter_context(
                    patch(
                        "app.application.agent_orchestrator.repair_advisor.chat_completion_openai_format",
                        AsyncMock(return_value=dict(task.get("llm_repair_response") or {})),
                    )
                )
            orchestrator = AgentOrchestrator(repository=repo)
            run = orchestrator.start_run_from_plan(
                user_id="eval-user",
                message=str(task.get("message") or task.get("id") or ""),
                plan=_build_plan(task),
                runtime_context={"source": "agent_eval", "task_id": str(task.get("id") or "")},
            )
            initial_status = run.status
            dispatch_before_approval = len(dispatches)

            if expected.get("continue_after_approval"):
                continued = orchestrator.continue_run(run.run_id, approved_by="agent-eval")
                if continued is not None:
                    run = continued

    _check_equal(
        checks,
        "initial_status",
        initial_status,
        expected.get("initial_status"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "final_status", run.status, expected.get("final_status"))
    _check_equal(
        checks,
        "dispatch_before_approval",
        dispatch_before_approval,
        expected.get("dispatch_before_approval"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "dispatch_count", len(dispatches), expected.get("dispatch_count"))
    _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
    _check_equal(
        checks,
        "artifact_count",
        len(run.artifacts),
        expected.get("artifact_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "repair_count",
        run.metadata.get("repair_count"),
        expected.get("repair_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "observation_count",
        run.metadata.get("observation_count"),
        expected.get("observation_count"),
        skip_when_expected_missing=True,
    )
    for key in (
        "ai_cost_budget_units",
        "ai_cost_budget_remaining_units",
        "ai_cost_budget_exceeded",
        "ai_cost_units_total",
        "llm_call_count",
        "llm_token_total",
        "llm_cost_units_total",
        "model_usage_entry_count",
        "model_usage_cost_units_total",
        "model_usage_ledger_status",
        "tool_usage_entry_count",
        "tool_usage_cost_units_total",
        "tool_usage_ledger_status",
        "tool_usage_refund_count",
        "tool_usage_refund_cost_units_total",
        "tool_usage_refund_status",
        "model_wallet_balance_units",
        "ai_wallet_balance_units",
        "model_wallet_balance_yuan",
        "ai_wallet_balance_yuan",
    ):
        _check_equal(
            checks,
            key,
            run.metadata.get(key),
            expected.get(key),
            skip_when_expected_missing=True,
        )
    _check_equal(
        checks,
        "market_wallet_call_count",
        len(market_calls),
        expected.get("market_wallet_call_count"),
        skip_when_expected_missing=True,
    )
    if len(market_calls) >= 3 and "market_wallet_refund_amount_yuan" in expected:
        _check_equal(
            checks,
            "market_wallet.calls[2].json.refund_amount",
            (market_calls[2].get("json") or {}).get("refund_amount"),
            expected.get("market_wallet_refund_amount_yuan"),
        )
    if run.llm_calls:
        call = run.llm_calls[0]
        for key in ("provider_id", "provider", "model", "billing_status", "billing_source"):
            expected_key = f"llm_{key}"
            if expected_key in expected:
                _check_equal(
                    checks,
                    f"llm_calls[0].{key}",
                    getattr(call, key),
                    expected.get(expected_key),
                )
    _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    _check_step_attempts(checks, run.steps, list(expected.get("step_attempt_counts") or []))
    _check_final_step_params(checks, run.steps, dict(expected.get("final_step_params") or {}))
    _check_final_node_outputs(checks, run.final_output, dict(expected.get("final_node_outputs") or {}))
    if run.artifacts and "artifact_type" in expected:
        _check_equal(
            checks,
            "artifacts[0].artifact_type",
            run.artifacts[0].artifact_type,
            expected.get("artifact_type"),
        )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    _check_step_errors(checks, run.steps, list(expected.get("step_errors") or []))
    return _result(
        task,
        checks,
        {"run": run.to_dict(), "dispatches": dispatches, "market_calls": market_calls},
    )


def _run_xcauto_credentials_task(task: dict[str, Any]) -> dict[str, Any]:
    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    with _patched_llm_env(dict(task.get("env") or {})):
        from app.infrastructure.llm.providers.credentials import (
            resolve_default_chat_model,
            resolve_default_openai_provider,
            resolve_openai_env_credentials,
            resolve_xcauto_credentials,
        )

        creds = resolve_xcauto_credentials()
        api_key, base_url = resolve_openai_env_credentials()
        actual = {
            "provider": resolve_default_openai_provider(),
            "model": resolve_default_chat_model(),
            "api_key": creds.api_key if creds else "",
            "api_url": creds.api_url if creds else "",
            "openai_api_key": api_key,
            "openai_base_url": base_url,
            "active_provider": _resolve_active_provider_id(),
        }

    for key, expected_value in expected.items():
        _check_equal(checks, key, actual.get(key), expected_value)
    return _result(task, checks, {"actual": actual})


def _resolve_active_provider_id() -> str:
    registry = None
    try:
        import app.infrastructure.llm.providers.registry as registry

        registry._registry = None
        provider = registry.get_active_provider()
        return str(getattr(provider, "provider_id", "") or "") if provider is not None else ""
    finally:
        if registry is not None:
            registry._registry = None


def _run_llm_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.services.conversation.api import ApiMixin

    class EvalApi(ApiMixin):
        def __init__(self) -> None:
            self._deepseek_async_client = None
            self._deepseek_async_loop = None
            self.model = "xcauto-account"

    provider = SimpleNamespace(
        provider_id="openai_compatible",
        _adapter=SimpleNamespace(provider_name="xcauto", model_name="xcauto-account"),
        chat_completion=AsyncMock(
            return_value={
                "choices": [{"message": {"content": "ok"}}],
                "model": "xcauto-account",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        ),
    )
    service = EvalApi()
    with (
        patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ),
        patch("app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"),
    ):
        result = asyncio.run(service.call_llm_api([{"role": "user", "content": "hi"}]))

    trace = dict((result or {}).get("_xcagi_trace") or {})
    checks: list[dict[str, Any]] = []
    for key, expected_value in dict(task.get("expected") or {}).items():
        _check_equal(checks, key, trace.get(key), expected_value)
    _check_equal(checks, "last_trace", getattr(service, "_last_llm_trace", {}), trace)
    return _result(task, checks, {"trace": trace})


class _EvalMarketWalletResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body, ensure_ascii=False, default=str)

    def json(self) -> dict[str, Any]:
        return self._body


class _EvalMarketWalletClient:
    def __init__(self, responses: list[_EvalMarketWalletResponse], calls: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._calls = calls

    def __enter__(self) -> _EvalMarketWalletClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def post(
        self,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> _EvalMarketWalletResponse:
        self._calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        if not self._responses:
            return _EvalMarketWalletResponse(500, {"ok": False, "message": "missing eval response"})
        return self._responses.pop(0)


def _market_wallet_eval_responses(task: dict[str, Any]) -> list[_EvalMarketWalletResponse]:
    configured = task.get("market_wallet_responses")
    if isinstance(configured, list) and configured:
        return [
            _EvalMarketWalletResponse(
                int(row.get("status_code") or 200),
                dict(row.get("body") or {}),
            )
            for row in configured
            if isinstance(row, dict)
        ]
    return [
        _EvalMarketWalletResponse(
            200,
            {
                "ok": True,
                "hold": {"hold_no": "AIH-EVAL", "amount": "0.02", "status": "held"},
                "balance": "9.98",
            },
        ),
        _EvalMarketWalletResponse(
            200,
            {
                "ok": True,
                "hold": {
                    "hold_no": "AIH-EVAL",
                    "amount": "0.02",
                    "settled_amount": "0.02",
                    "status": "settled",
                },
                "balance": "9.98",
            },
        ),
    ]


def _minimal_pdf_bytes(text: str) -> bytes:
    safe = (
        str(text or "")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\n", " ")
    )
    stream = f"BT\n/F1 18 Tf\n72 720 Td\n({safe}) Tj\nET\n".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")
    pdf += (
        b"trailer\n"
        + f"<< /Root 1 0 R /Size {len(objects) + 1} >>\n".encode("ascii")
        + f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return pdf


def _run_dataset_rag_document_qa_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        service = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        document_text = str(task.get("document_text") or "")
        source = str(task.get("source") or "document.txt")
        if str(task.get("file_kind") or "").lower() == "pdf":
            file_path = tmp_path / source
            file_path.write_bytes(_minimal_pdf_bytes(document_text))
            ingest_result = service.ingest_document(
                dataset_id=str(task.get("dataset_id") or "eval"),
                file_path=str(file_path),
                source=source,
                chunk_strategy=str(task.get("chunk_strategy") or "fixed"),
                chunk_size=int(task.get("chunk_size") or 500),
                chunk_overlap=int(task.get("chunk_overlap") or 50),
            )
        else:
            ingest_result = service.ingest_document(
                dataset_id=str(task.get("dataset_id") or "eval"),
                text=document_text,
                source=source,
                chunk_strategy=str(task.get("chunk_strategy") or "fixed"),
                chunk_size=int(task.get("chunk_size") or 500),
                chunk_overlap=int(task.get("chunk_overlap") or 50),
            )
        answer_result = service.answer(
            dataset_id=str(task.get("dataset_id") or "eval"),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 5),
        )
        status_result = service.status(str(task.get("dataset_id") or "eval"))
        reloaded_service = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        reload_answer_result = reloaded_service.answer(
            dataset_id=str(task.get("dataset_id") or "eval"),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 5),
        )
        reload_status_result = reloaded_service.status(str(task.get("dataset_id") or "eval"))

    _check_equal(checks, "ingest.success", ingest_result.get("success"), True)
    document = ingest_result.get("document") if isinstance(ingest_result.get("document"), dict) else {}
    _check_equal(
        checks,
        "document.parser",
        document.get("parser"),
        expected.get("parser"),
        skip_when_expected_missing=True,
    )
    if "chunk_count_min" in expected:
        actual_count = int(ingest_result.get("chunk_count") or 0)
        checks.append(
            {
                "name": "chunk_count_min",
                "passed": actual_count >= int(expected.get("chunk_count_min") or 0),
                "actual": actual_count,
                "expected": expected.get("chunk_count_min"),
            }
        )
    _check_equal(checks, "answer.success", answer_result.get("success"), True)
    if "answer_contains" in expected:
        checks.append(
            {
                "name": "answer_contains",
                "passed": str(expected.get("answer_contains") or "") in str(
                    answer_result.get("answer") or ""
                ),
                "actual": answer_result.get("answer"),
                "expected": expected.get("answer_contains"),
            }
        )
    citations = answer_result.get("citations") if isinstance(answer_result.get("citations"), list) else []
    if "citation_count_min" in expected:
        checks.append(
            {
                "name": "citation_count_min",
                "passed": len(citations) >= int(expected.get("citation_count_min") or 0),
                "actual": len(citations),
                "expected": expected.get("citation_count_min"),
            }
        )
    if citations and "first_citation_source_contains" in expected:
        source_url = str(citations[0].get("source_url") or "")
        checks.append(
            {
                "name": "citations[0].source_url_contains",
                "passed": str(expected.get("first_citation_source_contains") or "") in source_url,
                "actual": source_url,
                "expected": expected.get("first_citation_source_contains"),
            }
        )
    _check_equal(
        checks,
        "status.document_count",
        status_result.get("document_count"),
        expected.get("document_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "reload.status.document_count",
        reload_status_result.get("document_count"),
        expected.get("reload_document_count"),
        skip_when_expected_missing=True,
    )
    if "reload_answer_contains" in expected:
        checks.append(
            {
                "name": "reload_answer_contains",
                "passed": str(expected.get("reload_answer_contains") or "") in str(
                    reload_answer_result.get("answer") or ""
                ),
                "actual": reload_answer_result.get("answer"),
                "expected": expected.get("reload_answer_contains"),
            }
        )
    reload_citations = (
        reload_answer_result.get("citations")
        if isinstance(reload_answer_result.get("citations"), list)
        else []
    )
    if "reload_citation_count_min" in expected:
        checks.append(
            {
                "name": "reload_citation_count_min",
                "passed": len(reload_citations) >= int(
                    expected.get("reload_citation_count_min") or 0
                ),
                "actual": len(reload_citations),
                "expected": expected.get("reload_citation_count_min"),
            }
        )
    return _result(
        task,
        checks,
        {
            "ingest": ingest_result,
            "answer": answer_result,
            "status": status_result,
            "reload_answer": reload_answer_result,
            "reload_status": reload_status_result,
        },
    )


def _run_dataset_rag_governance_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    def embedder(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(lowered.count("xcauto")),
            float(lowered.count("deepseek")),
            float(len(lowered.split())),
        ]

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        service = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        ingests: list[dict[str, Any]] = []
        for document in list(task.get("documents") or []):
            if not isinstance(document, dict):
                continue
            ingests.append(
                service.ingest_document(
                    dataset_id=str(task.get("dataset_id") or "eval-governed"),
                    tenant_id=str(document.get("tenant_id") or ""),
                    version=str(document.get("version") or ""),
                    source=str(document.get("source") or "document.md"),
                    text=str(document.get("text") or ""),
                    chunk_strategy=str(document.get("chunk_strategy") or "fixed"),
                    metadata=dict(document.get("metadata") or {}),
                )
            )
        latest_answer = service.answer(
            dataset_id=str(task.get("dataset_id") or "eval-governed"),
            tenant_id=str(task.get("tenant_id") or ""),
            version=str(task.get("version") or "latest"),
            metadata_filter=dict(task.get("metadata_filter") or {}),
            rerank=bool(task.get("rerank", True)),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 1),
        )
        status = service.status(str(task.get("dataset_id") or "eval-governed"))
        reloaded = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        reload_answer = reloaded.answer(
            dataset_id=str(task.get("dataset_id") or "eval-governed"),
            tenant_id=str(task.get("tenant_id") or ""),
            version=str(task.get("version") or "latest"),
            metadata_filter=dict(task.get("metadata_filter") or {}),
            rerank=bool(task.get("rerank", True)),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 1),
        )
        reload_status = reloaded.status(str(task.get("dataset_id") or "eval-governed"))

    _check_equal(checks, "ingest_count", len(ingests), expected.get("ingest_count"))
    _check_equal(checks, "all_ingests_success", all(item.get("success") for item in ingests), True)
    if "latest_answer_contains" in expected:
        checks.append(
            {
                "name": "latest_answer_contains",
                "passed": str(expected.get("latest_answer_contains") or "") in str(
                    latest_answer.get("answer") or ""
                ),
                "actual": latest_answer.get("answer"),
                "expected": expected.get("latest_answer_contains"),
            }
        )
    if "latest_answer_not_contains" in expected:
        checks.append(
            {
                "name": "latest_answer_not_contains",
                "passed": str(expected.get("latest_answer_not_contains") or "") not in str(
                    latest_answer.get("answer") or ""
                ),
                "actual": latest_answer.get("answer"),
                "expected": expected.get("latest_answer_not_contains"),
            }
        )
    chunks = latest_answer.get("chunks") if isinstance(latest_answer.get("chunks"), list) else []
    first_metadata = (
        chunks[0].get("metadata")
        if chunks and isinstance(chunks[0], dict) and isinstance(chunks[0].get("metadata"), dict)
        else {}
    )
    _check_equal(
        checks,
        "chunks[0].metadata.tenant_id",
        first_metadata.get("tenant_id"),
        expected.get("tenant_id"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "chunks[0].metadata.document_version",
        first_metadata.get("document_version"),
        expected.get("document_version"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "chunks[0].metadata.private_embedding_absent",
        "_embedding" not in first_metadata,
        True,
    )
    index = status.get("index") if isinstance(status.get("index"), dict) else {}
    reload_index = reload_status.get("index") if isinstance(reload_status.get("index"), dict) else {}
    _check_equal(
        checks,
        "status.index.embedding_persisted",
        index.get("embedding_persisted"),
        expected.get("embedding_persisted"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "reload.index.embedding_count",
        reload_index.get("embedding_count"),
        index.get("embedding_count"),
    )
    if "reload_answer_contains" in expected:
        checks.append(
            {
                "name": "reload_answer_contains",
                "passed": str(expected.get("reload_answer_contains") or "") in str(
                    reload_answer.get("answer") or ""
                ),
                "actual": reload_answer.get("answer"),
                "expected": expected.get("reload_answer_contains"),
            }
        )
    return _result(
        task,
        checks,
        {
            "ingests": ingests,
            "answer": latest_answer,
            "status": status,
            "reload_answer": reload_answer,
            "reload_status": reload_status,
        },
    )


def _run_dataset_rag_version_ops_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    def embedder(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(len(lowered)),
            float(lowered.count("xcauto")),
            float(lowered.count("local")),
        ]

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    dataset_id = str(task.get("dataset_id") or "versioned-eval")
    source = str(task.get("source") or "policy.md")
    tenant_id = str(task.get("tenant_id") or "tenant-a")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        service = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        ingests: list[dict[str, Any]] = []
        for document in list(task.get("documents") or []):
            if not isinstance(document, dict):
                continue
            ingests.append(
                service.ingest_document(
                    dataset_id=dataset_id,
                    tenant_id=tenant_id,
                    source=source,
                    text=str(document.get("text") or ""),
                    chunk_strategy=str(document.get("chunk_strategy") or "fixed"),
                    metadata=dict(document.get("metadata") or {}),
                )
            )
        diff = service.diff_versions(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            source=source,
            from_version=str(task.get("from_version") or "1"),
            to_version=str(task.get("to_version") or "latest"),
        )
        rollback = service.rollback_document_version(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            source=source,
            target_version=str(task.get("rollback_target_version") or "1"),
            metadata=dict(task.get("rollback_metadata") or {}),
        )
        latest_answer = service.answer(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            version="latest",
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 1),
        )
        rebuild = service.start_rebuild_index(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            metadata_filter=dict(task.get("metadata_filter") or {}),
            background=False,
        )
        job_id = str((rebuild.get("job") or {}).get("job_id") or "")
        job_status = service.get_rebuild_job(dataset_id, job_id)
        status = service.status(dataset_id)
        reloaded = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
        )
        reload_status = reloaded.status(dataset_id)
        reload_job_status = reloaded.get_rebuild_job(dataset_id, job_id)

    _check_equal(checks, "ingest_count", len(ingests), expected.get("ingest_count"))
    _check_equal(checks, "all_ingests_success", all(item.get("success") for item in ingests), True)
    _check_equal(checks, "diff.success", diff.get("success"), True)
    _check_equal(checks, "diff.changed", diff.get("changed"), expected.get("diff_changed"))
    if "diff_added_contains" in expected:
        added = "\n".join(str(line) for line in diff.get("added_lines") or [])
        checks.append(
            {
                "name": "diff_added_contains",
                "passed": str(expected.get("diff_added_contains") or "") in added,
                "actual": added,
                "expected": expected.get("diff_added_contains"),
            }
        )
    if "diff_removed_contains" in expected:
        removed = "\n".join(str(line) for line in diff.get("removed_lines") or [])
        checks.append(
            {
                "name": "diff_removed_contains",
                "passed": str(expected.get("diff_removed_contains") or "") in removed,
                "actual": removed,
                "expected": expected.get("diff_removed_contains"),
            }
        )
    _check_equal(checks, "rollback.success", rollback.get("success"), True)
    rollback_doc = rollback.get("document") if isinstance(rollback.get("document"), dict) else {}
    _check_equal(
        checks,
        "rollback.document.version",
        rollback_doc.get("version"),
        expected.get("rollback_version"),
    )
    rollback_metadata = (
        rollback_doc.get("metadata") if isinstance(rollback_doc.get("metadata"), dict) else {}
    )
    _check_equal(
        checks,
        "rollback.metadata.rollback_from_version",
        rollback_metadata.get("rollback_from_version"),
        expected.get("rollback_from_version"),
        skip_when_expected_missing=True,
    )
    if "latest_after_rollback_contains" in expected:
        checks.append(
            {
                "name": "latest_after_rollback_contains",
                "passed": str(expected.get("latest_after_rollback_contains") or "") in str(
                    latest_answer.get("answer") or ""
                ),
                "actual": latest_answer.get("answer"),
                "expected": expected.get("latest_after_rollback_contains"),
            }
        )
    _check_equal(checks, "rebuild.success", rebuild.get("success"), True)
    _check_equal(
        checks,
        "rebuild.job.status",
        (rebuild.get("job") or {}).get("status"),
        expected.get("rebuild_status"),
    )
    _check_equal(
        checks,
        "job_status.job.status",
        (job_status.get("job") or {}).get("status"),
        expected.get("rebuild_status"),
    )
    _check_equal(
        checks,
        "status.rebuild_job_count",
        status.get("rebuild_job_count"),
        expected.get("rebuild_job_count"),
    )
    _check_equal(
        checks,
        "reload_status.document_count",
        reload_status.get("document_count"),
        expected.get("reload_document_count"),
    )
    _check_equal(
        checks,
        "reload_job_status.job.status",
        (reload_job_status.get("job") or {}).get("status"),
        expected.get("rebuild_status"),
    )
    return _result(
        task,
        checks,
        {
            "ingests": ingests,
            "diff": diff,
            "rollback": rollback,
            "latest_answer": latest_answer,
            "rebuild": rebuild,
            "job_status": job_status,
            "status": status,
            "reload_status": reload_status,
            "reload_job_status": reload_job_status,
        },
    )


def _run_dataset_rag_rbac_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import (
        DatasetAccessContext,
        DatasetRagApplicationService,
    )

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    dataset_id = str(task.get("dataset_id") or "secure-eval")
    admin = DatasetAccessContext(
        actor_id="admin",
        permissions=frozenset({"dataset.admin"}),
        is_admin=True,
    )
    tenant_id = str(task.get("tenant_id") or "tenant-a")
    other_tenant_id = str(task.get("other_tenant_id") or "tenant-b")
    tenant_reader = DatasetAccessContext(
        actor_id="tenant-reader",
        tenant_id=tenant_id,
        permissions=frozenset({"dataset.read"}),
    )
    tenant_writer = DatasetAccessContext(
        actor_id="tenant-writer",
        tenant_id=tenant_id,
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    other_reader = DatasetAccessContext(
        actor_id="other-reader",
        tenant_id=other_tenant_id,
        permissions=frozenset({"dataset.read"}),
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        service = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "dataset_store.json",
        )
        own_ingest = service.ingest_document(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            source=str(task.get("source") or "policy.md"),
            text=str(task.get("own_text") or "Tenant A policy uses XCauto."),
            chunk_strategy="fixed",
            access_context=admin,
        )
        other_ingest = service.ingest_document(
            dataset_id=dataset_id,
            tenant_id=other_tenant_id,
            source=str(task.get("source") or "policy.md"),
            text=str(task.get("other_text") or "Tenant B policy mentions DeepSeek."),
            chunk_strategy="fixed",
            access_context=admin,
        )
        own_answer = service.answer(
            dataset_id=dataset_id,
            query=str(task.get("query") or "Which model is in my policy?"),
            top_k=2,
            access_context=tenant_reader,
        )
        cross_answer = service.answer(
            dataset_id=dataset_id,
            tenant_id=other_tenant_id,
            query=str(task.get("cross_query") or "Which model is in tenant B policy?"),
            access_context=tenant_reader,
        )
        write_denied = service.ingest_document(
            dataset_id=dataset_id,
            source="denied.md",
            text="read-only users cannot write",
            access_context=tenant_reader,
        )
        implicit_tenant_write = service.ingest_document(
            dataset_id=dataset_id,
            source="writer.md",
            text=str(task.get("writer_text") or "Tenant A writer can append a policy."),
            chunk_strategy="fixed",
            access_context=tenant_writer,
        )
        scoped_status = service.status(dataset_id, access_context=tenant_reader)
        admin_status = service.status(dataset_id, access_context=admin)
        cross_delete = service.delete_document(
            dataset_id,
            str((other_ingest.get("document") or {}).get("document_id") or ""),
            access_context=tenant_writer,
        )
        rebuild = service.start_rebuild_index(
            dataset_id=dataset_id,
            background=False,
            access_context=tenant_writer,
        )
        job_id = str((rebuild.get("job") or {}).get("job_id") or "")
        cross_job = service.get_rebuild_job(dataset_id, job_id, access_context=other_reader)
        reloaded = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "dataset_store.json",
        )
        reload_scoped_status = reloaded.status(dataset_id, access_context=tenant_reader)

    _check_equal(checks, "own_ingest.success", own_ingest.get("success"), True)
    _check_equal(checks, "other_ingest.success", other_ingest.get("success"), True)
    _check_equal(checks, "own_answer.success", own_answer.get("success"), True)
    if "own_answer_contains" in expected:
        checks.append(
            {
                "name": "own_answer_contains",
                "passed": str(expected.get("own_answer_contains") or "") in str(
                    own_answer.get("answer") or ""
                ),
                "actual": own_answer.get("answer"),
                "expected": expected.get("own_answer_contains"),
            }
        )
    if "own_answer_not_contains" in expected:
        checks.append(
            {
                "name": "own_answer_not_contains",
                "passed": str(expected.get("own_answer_not_contains") or "") not in str(
                    own_answer.get("answer") or ""
                ),
                "actual": own_answer.get("answer"),
                "expected": expected.get("own_answer_not_contains"),
            }
        )
    _check_equal(
        checks,
        "cross_answer.error_code",
        cross_answer.get("error_code"),
        expected.get("permission_error_code"),
    )
    _check_equal(
        checks,
        "write_denied.required_permission",
        write_denied.get("required_permission"),
        expected.get("write_permission"),
    )
    _check_equal(
        checks,
        "implicit_tenant_write.document.tenant_id",
        (implicit_tenant_write.get("document") or {}).get("tenant_id"),
        tenant_id,
    )
    _check_equal(
        checks,
        "scoped_status.document_count",
        scoped_status.get("document_count"),
        expected.get("scoped_document_count"),
    )
    _check_equal(
        checks,
        "scoped_status.tenant_ids",
        scoped_status.get("tenant_ids"),
        expected.get("scoped_tenant_ids"),
    )
    _check_equal(
        checks,
        "admin_status.document_count",
        admin_status.get("document_count"),
        expected.get("admin_document_count"),
    )
    _check_equal(
        checks,
        "cross_delete.error_code",
        cross_delete.get("error_code"),
        expected.get("permission_error_code"),
    )
    _check_equal(checks, "rebuild.success", rebuild.get("success"), True)
    _check_equal(
        checks,
        "rebuild.job.tenant_id",
        (rebuild.get("job") or {}).get("tenant_id"),
        tenant_id,
    )
    _check_equal(
        checks,
        "cross_job.error_code",
        cross_job.get("error_code"),
        expected.get("permission_error_code"),
    )
    _check_equal(
        checks,
        "reload_scoped_status.document_count",
        reload_scoped_status.get("document_count"),
        expected.get("scoped_document_count"),
    )
    return _result(
        task,
        checks,
        {
            "own_ingest": own_ingest,
            "other_ingest": other_ingest,
            "own_answer": own_answer,
            "cross_answer": cross_answer,
            "write_denied": write_denied,
            "implicit_tenant_write": implicit_tenant_write,
            "scoped_status": scoped_status,
            "admin_status": admin_status,
            "cross_delete": cross_delete,
            "rebuild": rebuild,
            "cross_job": cross_job,
            "reload_scoped_status": reload_scoped_status,
        },
    )


def _run_dataset_rag_rebuild_queue_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import (
        DatasetAccessContext,
        DatasetRagApplicationService,
    )

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    dataset_id = str(task.get("dataset_id") or "queue-eval")
    tenant_id = str(task.get("tenant_id") or "tenant-a")
    writer = DatasetAccessContext(
        actor_id="queue-writer",
        tenant_id=tenant_id,
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        service = DatasetRagApplicationService(
            embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
            allowed_roots=[tmp_path],
            storage_path=storage_path,
            max_concurrent_rebuild_jobs=int(task.get("max_concurrent_rebuild_jobs") or 1),
            rebuild_workers_enabled=False,
        )
        ingest = service.ingest_document(
            dataset_id=dataset_id,
            source=str(task.get("source") or "policy.md"),
            text=str(task.get("document_text") or "Tenant A queue policy uses XCauto."),
            chunk_strategy="fixed",
            access_context=writer,
        )
        first = service.start_rebuild_index(
            dataset_id=dataset_id,
            background=True,
            access_context=writer,
        )
        second = service.start_rebuild_index(
            dataset_id=dataset_id,
            background=True,
            access_context=writer,
        )
        first_id = str((first.get("job") or {}).get("job_id") or "")
        second_id = str((second.get("job") or {}).get("job_id") or "")
        queued_status = service.status(dataset_id, access_context=writer)
        cancelled = service.cancel_rebuild_job(dataset_id, second_id, access_context=writer)
        drained = service.drain_rebuild_queue()
        final_status = service.status(dataset_id, access_context=writer)
        first_job = service.get_rebuild_job(dataset_id, first_id, access_context=writer)
        second_job = service.get_rebuild_job(dataset_id, second_id, access_context=writer)
        reloaded = DatasetRagApplicationService(
            embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
            allowed_roots=[tmp_path],
            storage_path=storage_path,
            max_concurrent_rebuild_jobs=int(task.get("max_concurrent_rebuild_jobs") or 1),
            rebuild_workers_enabled=False,
        )
        reload_status = reloaded.status(dataset_id, access_context=writer)

    _check_equal(checks, "ingest.success", ingest.get("success"), True)
    _check_equal(checks, "first.job.status", (first.get("job") or {}).get("status"), "queued")
    _check_equal(checks, "first.job.queue_position", (first.get("job") or {}).get("queue_position"), 1)
    _check_equal(checks, "second.job.status", (second.get("job") or {}).get("status"), "queued")
    _check_equal(checks, "second.job.queue_position", (second.get("job") or {}).get("queue_position"), 2)
    queue = queued_status.get("rebuild_queue") if isinstance(queued_status.get("rebuild_queue"), dict) else {}
    _check_equal(checks, "queued_status.rebuild_queue.queued", queue.get("queued"), 2)
    _check_equal(
        checks,
        "queued_status.rebuild_queue.worker_enabled",
        queue.get("worker_enabled"),
        expected.get("worker_enabled"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "cancelled.job.status",
        (cancelled.get("job") or {}).get("status"),
        expected.get("cancelled_status"),
    )
    _check_equal(
        checks,
        "drained.drained_count",
        drained.get("drained_count"),
        expected.get("drained_count"),
    )
    _check_equal(
        checks,
        "first_job.job.status",
        (first_job.get("job") or {}).get("status"),
        expected.get("completed_status"),
    )
    _check_equal(
        checks,
        "second_job.job.status",
        (second_job.get("job") or {}).get("status"),
        expected.get("cancelled_status"),
    )
    final_queue = final_status.get("rebuild_queue") if isinstance(final_status.get("rebuild_queue"), dict) else {}
    _check_equal(checks, "final_queue.completed", final_queue.get("completed"), expected.get("completed_count"))
    _check_equal(checks, "final_queue.cancelled", final_queue.get("cancelled"), expected.get("cancelled_count"))
    _check_equal(checks, "final_queue.queued", final_queue.get("queued"), 0)
    reload_queue = (
        reload_status.get("rebuild_queue")
        if isinstance(reload_status.get("rebuild_queue"), dict)
        else {}
    )
    _check_equal(
        checks,
        "reload_queue.completed",
        reload_queue.get("completed"),
        expected.get("completed_count"),
    )
    _check_equal(
        checks,
        "reload_queue.cancelled",
        reload_queue.get("cancelled"),
        expected.get("cancelled_count"),
    )
    return _result(
        task,
        checks,
        {
            "ingest": ingest,
            "first": first,
            "second": second,
            "queued_status": queued_status,
            "cancelled": cancelled,
            "drained": drained,
            "final_status": final_status,
            "first_job": first_job,
            "second_job": second_job,
            "reload_status": reload_status,
        },
    )


def _run_dataset_rag_vector_backend_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService
    from app.infrastructure.rag.dataset_vector_index import DatasetVectorSQLiteIndex

    def embedder(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(lowered.count("xcauto")),
            float(lowered.count("deepseek")),
            float(len(lowered.split())),
        ]

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    dataset_id = str(task.get("dataset_id") or "vector-eval")
    tenant_id = str(task.get("tenant_id") or "tenant-a")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        vector_path = tmp_path / "dataset_vectors.sqlite"
        service = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
            vector_index_backend_name="sqlite",
            vector_index_path=vector_path,
        )
        ingests: list[dict[str, Any]] = []
        for document in list(task.get("documents") or []):
            if not isinstance(document, dict):
                continue
            ingests.append(
                service.ingest_document(
                    dataset_id=dataset_id,
                    tenant_id=str(document.get("tenant_id") or tenant_id),
                    source=str(document.get("source") or "policy.md"),
                    text=str(document.get("text") or ""),
                    chunk_strategy=str(document.get("chunk_strategy") or "fixed"),
                    metadata=dict(document.get("metadata") or {}),
                )
            )
        answer = service.answer(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            version=str(task.get("version") or "latest"),
            metadata_filter=dict(task.get("metadata_filter") or {}),
            rerank=bool(task.get("rerank", True)),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 1),
        )
        status = service.status(dataset_id)
        backend = DatasetVectorSQLiteIndex(vector_path)
        backend_status = backend.status(dataset_id)
        backend_hits = backend.query(
            dataset_id,
            embedder(str(task.get("query") or "")),
            tenant_id=tenant_id,
            version=str(task.get("version") or "latest"),
            metadata_filter=dict(task.get("metadata_filter") or {}),
            top_k=5,
        )
        reloaded = DatasetRagApplicationService(
            embedder=embedder,
            allowed_roots=[tmp_path],
            storage_path=storage_path,
            vector_index_backend_name="sqlite",
            vector_index_path=vector_path,
        )
        reload_answer = reloaded.answer(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            version=str(task.get("version") or "latest"),
            metadata_filter=dict(task.get("metadata_filter") or {}),
            rerank=bool(task.get("rerank", True)),
            query=str(task.get("query") or ""),
            top_k=int(task.get("top_k") or 1),
        )
        reload_status = reloaded.status(dataset_id)

    _check_equal(checks, "ingest_count", len(ingests), expected.get("ingest_count"))
    _check_equal(checks, "all_ingests_success", all(item.get("success") for item in ingests), True)
    _check_equal(checks, "answer.success", answer.get("success"), True)
    _check_equal(
        checks,
        "answer.vector_backend_used",
        answer.get("vector_backend_used"),
        expected.get("vector_backend_used"),
    )
    _check_equal(
        checks,
        "answer.index.query_backend",
        (answer.get("index") or {}).get("query_backend"),
        expected.get("query_backend"),
    )
    if "answer_contains" in expected:
        checks.append(
            {
                "name": "answer_contains",
                "passed": str(expected.get("answer_contains") or "") in str(
                    answer.get("answer") or ""
                ),
                "actual": answer.get("answer"),
                "expected": expected.get("answer_contains"),
            }
        )
    if "answer_not_contains" in expected:
        checks.append(
            {
                "name": "answer_not_contains",
                "passed": str(expected.get("answer_not_contains") or "") not in str(
                    answer.get("answer") or ""
                ),
                "actual": answer.get("answer"),
                "expected": expected.get("answer_not_contains"),
            }
        )
    index = status.get("index") if isinstance(status.get("index"), dict) else {}
    _check_equal(
        checks,
        "status.index.vector_backend_name",
        index.get("vector_backend_name"),
        expected.get("vector_backend_name"),
    )
    _check_equal(
        checks,
        "status.index.vector_backend_persistent",
        index.get("vector_backend_persistent"),
        expected.get("vector_backend_persistent"),
    )
    _check_equal(
        checks,
        "status.index.vector_backend_sync_status",
        index.get("vector_backend_sync_status"),
        expected.get("vector_backend_sync_status"),
    )
    _check_equal(
        checks,
        "backend_status.index_exists",
        backend_status.get("index_exists"),
        True,
    )
    _check_equal(
        checks,
        "backend_status.chunk_count",
        backend_status.get("chunk_count"),
        status.get("chunk_count"),
    )
    first_hit_metadata = backend_hits[0].metadata if backend_hits else {}
    _check_equal(
        checks,
        "backend_hits[0].metadata.tenant_id",
        first_hit_metadata.get("tenant_id"),
        expected.get("tenant_id"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "backend_hits[0].metadata.document_version",
        first_hit_metadata.get("document_version"),
        expected.get("document_version"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "reload_answer.vector_backend_used",
        reload_answer.get("vector_backend_used"),
        expected.get("vector_backend_used"),
    )
    if "reload_answer_contains" in expected:
        checks.append(
            {
                "name": "reload_answer_contains",
                "passed": str(expected.get("reload_answer_contains") or "") in str(
                    reload_answer.get("answer") or ""
                ),
                "actual": reload_answer.get("answer"),
                "expected": expected.get("reload_answer_contains"),
            }
        )
    reload_index = reload_status.get("index") if isinstance(reload_status.get("index"), dict) else {}
    _check_equal(
        checks,
        "reload_status.index.vector_backend_chunk_count",
        reload_index.get("vector_backend_chunk_count"),
        status.get("chunk_count"),
    )
    return _result(
        task,
        checks,
        {
            "ingests": ingests,
            "answer": answer,
            "status": status,
            "backend_status": backend_status,
            "backend_hits": [
                {
                    "text": hit.text,
                    "score": hit.score,
                    "metadata": hit.metadata,
                    "source": hit.source,
                }
                for hit in backend_hits
            ],
            "reload_answer": reload_answer,
            "reload_status": reload_status,
        },
    )


def _run_agent_run_llm_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.infrastructure.billing.model_usage import get_model_wallet, set_model_wallet_balance

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    payload = dict(task.get("payload") or {})
    market_calls: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger_path = str(Path(tmp_dir) / "model_usage_ledger.json")
        env_patch = {"MODEL_USAGE_LEDGER_PATH": ledger_path, "MODEL_USAGE_WALLET_REQUIRED": ""}
        if str(task.get("wallet_backend") or "").strip().lower() == "market":
            env_patch.update(
                {
                    "MODEL_USAGE_WALLET_BACKEND": "market",
                    "MODEL_USAGE_MARKET_BASE_URL": str(
                        task.get("market_base_url") or "http://market.eval"
                    ),
                    "MODEL_USAGE_MARKET_AUTH_TOKEN": str(
                        task.get("market_auth_token") or "eval-market-token"
                    ),
                    "MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT": str(
                        task.get("market_yuan_per_cost_unit") or "0.02"
                    ),
                }
            )
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
                    return_value=repo,
                )
            )
            if env_patch.get("MODEL_USAGE_WALLET_BACKEND") == "market":
                from app.infrastructure.billing import model_usage

                responses = _market_wallet_eval_responses(task)
                stack.enter_context(
                    patch.object(
                        model_usage.httpx,
                        "Client",
                        lambda *args, **kwargs: _EvalMarketWalletClient(responses, market_calls),
                    )
                )
            if "wallet_balance_units" in task:
                set_model_wallet_balance(
                    "eval-user",
                    int(task.get("wallet_balance_units") or 0),
                    reason="agent_eval",
                )
            result = attach_chat_trace_run(
                payload,
                message=str(task.get("message") or task.get("id") or ""),
                runtime_context={"source": "agent_eval", "task_id": str(task.get("id") or "")},
                user_id="eval-user",
                source="agent_eval",
                channel="eval_chat",
            )
            wallet_snapshot = get_model_wallet("eval-user")

    run = repo.get(str(result.get("run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "run_attached", run is not None, True)
    if run is None:
        return _result(task, checks, {"payload": result})

    _check_equal(checks, "llm_call_count", len(run.llm_calls), expected.get("llm_call_count"))
    _check_equal(
        checks,
        "llm_token_total",
        run.metadata.get("llm_token_total"),
        expected.get("llm_token_total"),
    )
    _check_equal(
        checks,
        "llm_cost_units_total",
        run.metadata.get("llm_cost_units_total"),
        expected.get("llm_cost_units_total"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "ai_cost_units_total",
        run.metadata.get("ai_cost_units_total"),
        expected.get("ai_cost_units_total"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "model_wallet_balance_units",
        run.metadata.get("model_wallet_balance_units"),
        expected.get("model_wallet_balance_units"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "wallet.balance_units",
        wallet_snapshot.get("balance_units"),
        expected.get("wallet_balance_units"),
        skip_when_expected_missing=True,
    )
    for key in (
        "model_usage_entry_count",
        "model_usage_cost_units_total",
        "model_usage_ledger_status",
    ):
        _check_equal(
            checks,
            key,
            run.metadata.get(key),
            expected.get(key),
            skip_when_expected_missing=True,
        )
    _check_equal(
        checks,
        "model_wallet_balance_yuan",
        run.metadata.get("model_wallet_balance_yuan"),
        expected.get("model_wallet_balance_yuan"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "market_wallet_call_count",
        len(market_calls),
        expected.get("market_wallet_call_count"),
        skip_when_expected_missing=True,
    )
    if market_calls and "market_wallet_amount_yuan" in expected:
        _check_equal(
            checks,
            "market_wallet.calls[0].json.amount",
            (market_calls[0].get("json") or {}).get("amount"),
            expected.get("market_wallet_amount_yuan"),
        )
    if market_calls and "market_wallet_authorization" in expected:
        _check_equal(
            checks,
            "market_wallet.calls[0].headers.Authorization",
            (market_calls[0].get("headers") or {}).get("Authorization"),
            expected.get("market_wallet_authorization"),
        )
    if run.llm_calls:
        call = run.llm_calls[0]
        for key in (
            "provider_id",
            "provider",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_units",
            "billing_status",
            "billing_source",
        ):
            if key in expected:
                _check_equal(checks, f"llm_calls[0].{key}", getattr(call, key), expected.get(key))
        wallet_debit = (
            call.metadata.get("wallet_debit")
            if isinstance(call.metadata.get("wallet_debit"), dict)
            else {}
        )
        for key in ("status", "amount_yuan", "balance_after_yuan", "hold_no"):
            expected_key = f"wallet_debit_{key}"
            if expected_key in expected:
                _check_equal(
                    checks,
                    f"llm_calls[0].metadata.wallet_debit.{key}",
                    wallet_debit.get(key),
                    expected.get(expected_key),
                )
        preauthorize_hold = (
            wallet_debit.get("preauthorize", {}).get("hold", {})
            if isinstance(wallet_debit.get("preauthorize"), dict)
            else {}
        )
        settle_hold = (
            wallet_debit.get("settle", {}).get("hold", {})
            if isinstance(wallet_debit.get("settle"), dict)
            else {}
        )
        if "wallet_debit_preauthorize_status" in expected:
            _check_equal(
                checks,
                "llm_calls[0].metadata.wallet_debit.preauthorize.hold.status",
                preauthorize_hold.get("status") if isinstance(preauthorize_hold, dict) else None,
                expected.get("wallet_debit_preauthorize_status"),
            )
        if "wallet_debit_settle_status" in expected:
            _check_equal(
                checks,
                "llm_calls[0].metadata.wallet_debit.settle.hold.status",
                settle_hold.get("status") if isinstance(settle_hold, dict) else None,
                expected.get("wallet_debit_settle_status"),
            )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(task, checks, {"run": run.to_dict(), "payload": result, "market_calls": market_calls})


def _run_agent_run_rag_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    payload = dict(task.get("payload") or {})
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message=str(task.get("message") or task.get("id") or ""),
            runtime_context={"source": "agent_eval", "task_id": str(task.get("id") or "")},
            user_id="eval-user",
            source="agent_eval",
            channel="eval_chat",
        )

    run = repo.get(str(result.get("run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "run_attached", run is not None, True)
    if run is None:
        return _result(task, checks, {"payload": result})

    _check_equal(
        checks,
        "retrieval_call_count",
        len(run.retrieval_calls),
        expected.get("retrieval_call_count"),
    )
    _check_equal(
        checks,
        "retrieval_chunk_count",
        run.metadata.get("retrieval_chunk_count"),
        expected.get("retrieval_chunk_count"),
    )
    _check_equal(checks, "citation_count", run.metadata.get("citation_count"), expected.get("citation_count"))
    if run.retrieval_calls:
        call = run.retrieval_calls[0]
        for key in ("query", "retriever", "source", "top_k", "status"):
            if key in expected:
                _check_equal(checks, f"retrieval_calls[0].{key}", getattr(call, key), expected.get(key))
        if "first_citation_source" in expected:
            first_source = str((call.citations[0] if call.citations else {}).get("source") or "")
            _check_equal(checks, "retrieval_calls[0].citations[0].source", first_source, expected.get("first_citation_source"))
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(task, checks, {"run": run.to_dict(), "payload": result})


def _run_agent_run_artifact_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import (
        get_dataset_rag_app_service,
        reset_dataset_rag_app_service_for_tests,
    )

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    payload = copy.deepcopy(dict(task.get("payload") or {}))
    answer_result: dict[str, Any] = {}
    reload_answer_result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        tmp_path = Path(tmp_dir)
        storage_path = tmp_path / "dataset_store.json"
        if str(task.get("file_kind") or "").lower() == "pdf":
            source = str(task.get("source") or "artifact.pdf")
            file_path = tmp_path / source
            file_path.write_bytes(_minimal_pdf_bytes(str(task.get("document_text") or "")))
            _inject_file_analysis_path(payload, file_path, source)
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {"DATASET_RAG_STORE_PATH": str(storage_path)},
                    clear=False,
                )
            )
            reset_dataset_rag_app_service_for_tests()
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
                    return_value=repo,
                )
            )
            result = attach_chat_trace_run(
                payload,
                message=str(task.get("message") or task.get("id") or ""),
                runtime_context={
                    "source": "agent_eval",
                    "task_id": str(task.get("id") or ""),
                    **dict(task.get("runtime_context") or {}),
                },
                user_id="eval-user",
                source="agent_eval",
                channel="eval_chat",
            )
            if expected.get("dataset_query"):
                answer_result = get_dataset_rag_app_service().answer(
                    dataset_id=str(expected.get("dataset_id") or "user_eval-user"),
                    query=str(expected.get("dataset_query") or ""),
                    top_k=int(expected.get("dataset_top_k") or 5),
                )
                reset_dataset_rag_app_service_for_tests()
                reload_answer_result = get_dataset_rag_app_service().answer(
                    dataset_id=str(expected.get("dataset_id") or "user_eval-user"),
                    query=str(expected.get("dataset_query") or ""),
                    top_k=int(expected.get("dataset_top_k") or 5),
                )
            reset_dataset_rag_app_service_for_tests()

    run = repo.get(str(result.get("run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "run_attached", run is not None, True)
    if run is None:
        return _result(task, checks, {"payload": result})

    _check_equal(checks, "artifact_count", len(run.artifacts), expected.get("artifact_count"))
    _check_equal(
        checks,
        "metadata.artifact_count",
        run.metadata.get("artifact_count"),
        expected.get("artifact_count"),
    )
    if run.artifacts:
        artifact = run.artifacts[0]
        for key in ("artifact_type", "source", "uri", "mime_type"):
            if key in expected:
                _check_equal(checks, f"artifacts[0].{key}", getattr(artifact, key), expected.get(key))
        if "first_field_name" in expected:
            first_field_name = str((artifact.fields[0] if artifact.fields else {}).get("name") or "")
            _check_equal(checks, "artifacts[0].fields[0].name", first_field_name, expected.get("first_field_name"))
    _check_equal(
        checks,
        "metadata.dataset_ingest_count",
        run.metadata.get("dataset_ingest_count"),
        expected.get("dataset_ingest_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "metadata.dataset_ids",
        run.metadata.get("dataset_ids"),
        expected.get("dataset_ids"),
        skip_when_expected_missing=True,
    )
    ingests = [
        item
        for item in run.metadata.get("dataset_ingests", [])
        if isinstance(item, dict)
    ]
    if ingests:
        for key in ("dataset_id", "parser", "source"):
            expected_key = f"dataset_ingest_{key}"
            if expected_key in expected:
                _check_equal(
                    checks,
                    f"metadata.dataset_ingests[0].{key}",
                    ingests[0].get(key),
                    expected.get(expected_key),
                )
    if "dataset_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_answer_contains",
                "passed": str(expected.get("dataset_answer_contains") or "") in str(
                    answer_result.get("answer") or ""
                ),
                "actual": answer_result.get("answer"),
                "expected": expected.get("dataset_answer_contains"),
            }
        )
    if "dataset_reload_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_reload_answer_contains",
                "passed": str(expected.get("dataset_reload_answer_contains") or "") in str(
                    reload_answer_result.get("answer") or ""
                ),
                "actual": reload_answer_result.get("answer"),
                "expected": expected.get("dataset_reload_answer_contains"),
            }
        )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "run": run.to_dict(),
            "payload": result,
            "dataset_answer": answer_result,
            "dataset_reload_answer": reload_answer_result,
        },
    )


def _run_multimodal_autonomous_plan_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.dataset_rag_app_service import (
        get_dataset_rag_app_service,
        reset_dataset_rag_app_service_for_tests,
    )

    expected = dict(task.get("expected") or {})
    runtime_context = copy.deepcopy(dict(task.get("runtime_context") or {}))
    answer_result: dict[str, Any] = {}
    reload_answer_result: dict[str, Any] = {}
    repo = InMemoryAgentRunRepository()
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        tmp_path = Path(tmp_dir)
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "DATASET_RAG_STORE_PATH": str(tmp_path / "dataset_store.json"),
                        "DATASET_RAG_VECTOR_INDEX_PATH": str(tmp_path / "dataset_vectors.sqlite3"),
                        "MODEL_USAGE_LEDGER_PATH": str(tmp_path / "model_usage_ledger.json"),
                        "MODEL_USAGE_WALLET_BACKEND": "audit",
                    },
                    clear=False,
                )
            )
            os.environ.pop("MODEL_USAGE_WALLET_REQUIRED", None)
            reset_dataset_rag_app_service_for_tests()
            mock_office_document = dict(task.get("mock_office_document") or {})
            if mock_office_document:
                file_name = str(mock_office_document.get("file_name") or "agent-eval.docx")
                pickup_token = str(mock_office_document.get("pickup_token") or "agent-eval-doc")
                content = str(mock_office_document.get("content") or "agent eval document").encode(
                    "utf-8"
                )
                stack.enter_context(
                    patch(
                        "app.services.kitten_ai_document.generate.generate_office_file",
                        return_value=(content, file_name),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.services.kitten_ai_document.pickup.store_document_pickup",
                        return_value=pickup_token,
                    )
                )
            run = AgentOrchestrator(repository=repo).start_run(
                user_id=str(task.get("user_id") or "eval-user"),
                message=str(task.get("message") or task.get("id") or ""),
                runtime_context=runtime_context,
            )
            initial_status = run.status
            if expected.get("continue_after_approval"):
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
                    continued = AgentOrchestrator(repository=repo).continue_run(
                        run.run_id,
                        approved_by="agent-eval",
                    )
                if continued is not None:
                    run = continued
            if expected.get("dataset_query"):
                answer_result = get_dataset_rag_app_service().answer(
                    dataset_id=str(
                        expected.get("dataset_id") or runtime_context.get("dataset_id") or ""
                    ),
                    query=str(expected.get("dataset_query") or ""),
                    top_k=int(expected.get("dataset_top_k") or 5),
                    tenant_id=str(
                        expected.get("tenant_id") or runtime_context.get("tenant_id") or ""
                    ),
                )
                reset_dataset_rag_app_service_for_tests()
                reload_answer_result = get_dataset_rag_app_service().answer(
                    dataset_id=str(
                        expected.get("dataset_id") or runtime_context.get("dataset_id") or ""
                    ),
                    query=str(expected.get("dataset_query") or ""),
                    top_k=int(expected.get("dataset_top_k") or 5),
                    tenant_id=str(
                        expected.get("tenant_id") or runtime_context.get("tenant_id") or ""
                    ),
                )
            reset_dataset_rag_app_service_for_tests()

    checks: list[dict[str, Any]] = []
    _check_equal(
        checks,
        "initial_status",
        initial_status,
        expected.get("initial_status"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "final_status", run.status, expected.get("final_status"))
    _check_equal(checks, "intent", run.intent, expected.get("intent"))
    _check_equal(
        checks,
        "plan_metadata.source",
        dict(run.metadata.get("plan") or {}).get("metadata", {}).get("source"),
        expected.get("plan_source"),
    )
    _check_equal(checks, "artifact_count", len(run.artifacts), expected.get("artifact_count"))
    _check_equal(
        checks,
        "metadata.dataset_ingest_count",
        run.metadata.get("dataset_ingest_count"),
        expected.get("dataset_ingest_count"),
    )
    _check_equal(
        checks,
        "metadata.dataset_ids",
        run.metadata.get("dataset_ids"),
        expected.get("dataset_ids"),
    )
    _check_equal(
        checks,
        "plan_metadata.excel_import_record_count",
        dict(run.metadata.get("plan") or {}).get("metadata", {}).get("excel_import_record_count"),
        expected.get("excel_import_record_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
    _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    _check_final_step_params(checks, run.steps, dict(expected.get("final_step_params") or {}))
    _check_final_node_outputs(checks, run.final_output, dict(expected.get("final_node_outputs") or {}))
    if "tool_answer_contains" in expected:
        answer = str((run.tool_calls[0].output if run.tool_calls else {}).get("answer") or "")
        checks.append(
            {
                "name": "tool_answer_contains",
                "passed": str(expected.get("tool_answer_contains") or "") in answer,
                "actual": answer,
                "expected": expected.get("tool_answer_contains"),
            }
        )
    if "dataset_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_answer_contains",
                "passed": str(expected.get("dataset_answer_contains") or "") in str(
                    answer_result.get("answer") or ""
                ),
                "actual": answer_result.get("answer"),
                "expected": expected.get("dataset_answer_contains"),
            }
        )
    if "dataset_reload_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_reload_answer_contains",
                "passed": str(expected.get("dataset_reload_answer_contains") or "") in str(
                    reload_answer_result.get("answer") or ""
                ),
                "actual": reload_answer_result.get("answer"),
                "expected": expected.get("dataset_reload_answer_contains"),
            }
        )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "run": run.to_dict(),
            "dataset_answer": answer_result,
            "dataset_reload_answer": reload_answer_result,
        },
    )


def _run_excel_vector_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.excel_vector import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "ingest").strip().lower()
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            if action == "query":
                service = Mock()
                service.query.return_value = dict(
                    task.get("mock_query_result")
                    or {
                        "success": True,
                        "index_id": "idx-eval",
                        "query": "5003",
                        "hits": [{"score": 0.91, "row": {"model_number": "5003"}}],
                    }
                )
                stack.enter_context(
                    patch(
                        "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
                        return_value=service,
                    )
                )
                response = client.post(
                    "/api/excel/vector/query",
                    json=dict(
                        task.get("body")
                        or {"index_id": "idx-eval", "query": "5003", "top_k": 3}
                    ),
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )
            else:
                service = Mock()
                service.ingest_excel.return_value = dict(
                    task.get("mock_ingest_result")
                    or {
                        "success": True,
                        "index_id": "idx-eval",
                        "chunk_count": 2,
                        "row_count": 8,
                    }
                )
                stack.enter_context(
                    patch(
                        "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
                        return_value=service,
                    )
                )
                response = client.post(
                    "/api/excel/vector/ingest",
                    json=dict(
                        task.get("body")
                        or {
                            "file_path": "/tmp/products.xlsx",
                            "index_name": "products",
                        }
                    ),
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_ocr_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.ocr import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "recognize").strip().lower()
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.recognize_file.return_value = dict(
        task.get("mock_recognize_result")
        or {
            "success": True,
            "message": "识别成功",
            "text": "购货单位：ACME Trading",
            "file_path": "/tmp/label.png",
        }
    )
    service.extract_structured_data.return_value = dict(
        task.get("mock_extract_result") or {"purchase_unit": "ACME Trading"}
    )
    service.analyze_text.return_value = dict(
        task.get("mock_analyze_result") or {"text_type": "order", "confidence": 0.67}
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch("app.fastapi_routes.ocr._get_ocr_service", return_value=service)
            )
            if action == "analyze":
                response = client.post(
                    "/api/ocr/analyze",
                    json=dict(
                        task.get("body")
                        or {"text": "订单编号：SO-1\n购货单位：ACME Trading"}
                    ),
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )
            elif action == "extract":
                response = client.post(
                    "/api/ocr/extract",
                    json=dict(task.get("body") or {"text": "购货单位：ACME Trading"}),
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )
            else:
                path = "/api/ocr/recognize-and-extract" if action == "recognize_and_extract" else "/api/ocr/recognize"
                response = client.post(
                    path,
                    data=dict(task.get("form") or {"file_path": "/tmp/label.png"}),
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_equal(
            checks,
            "artifact_count",
            len(run.artifacts),
            expected.get("artifact_count"),
            skip_when_expected_missing=True,
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_business_ocr_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.business_api import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = bool(task.get("mock_publish_result", True))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "FHD_BUSINESS_API_KEY": "",
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain)
            )
            response = client.post(
                "/api/business/ocr/recognize",
                json=dict(
                    task.get("body")
                    or {
                        "request_id": "ocr-req-eval",
                        "image_url": "https://example.invalid/label.png",
                        "ocr_type": "invoice",
                        "user_id": str(task.get("user_id") or "eval-user"),
                    }
                ),
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.event", payload.get("event"), expected.get("event"))
    _check_equal(checks, "payload.published", payload.get("published"), expected.get("published"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "publish_call_count": ocr_domain.emit_ocr_requested.call_count,
        },
    )


def _run_business_event_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.business_api import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "print_label").strip().lower() or "print_label"
    route_map = {
        "print_label": "/api/business/print/label",
        "inventory_update": "/api/business/inventory/update",
        "shipment_create": "/api/business/shipment/create",
    }
    path = route_map.get(action, "/api/business/print/label")
    body = dict(task.get("body") or {})
    if action == "print_label":
        body.setdefault("job_id", "print-job-eval")
        body.setdefault("document_name", "发货标签.pdf")
        body.setdefault("printer_id", "default")
        body.setdefault("copies", 1)
    elif action == "inventory_update":
        body.setdefault("product_id", "sku-1")
        body.setdefault("warehouse_id", "main")
        body.setdefault("delta", -2)
        body.setdefault("reason", "shipment")
        body.setdefault("new_quantity", 18)
    else:
        body.setdefault("unit_name", "ACME Trading")
        body.setdefault("items", [{"sku": "sku-1", "qty": 2}])
        body.setdefault("contact_person", "Lee")
        body.setdefault("contact_phone", "13800000000")

    repo = InMemoryAgentRunRepository()
    print_domain = Mock()
    print_domain.emit_job_submitted.return_value = bool(task.get("mock_publish_result", True))
    inventory_domain = Mock()
    inventory_domain.emit_stock_changed.return_value = bool(task.get("mock_publish_result", True))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "FHD_BUSINESS_API_KEY": "",
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch("app.neuro_bus.domains.print_domain.get_print_domain", return_value=print_domain)
            )
            stack.enter_context(
                patch(
                    "app.neuro_bus.domains.inventory_domain.get_inventory_domain",
                    return_value=inventory_domain,
                )
            )
            stack.enter_context(
                patch(
                    "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
                    return_value=bool(task.get("mock_publish_result", True)),
                )
            )
            response = client.post(
                path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.event", payload.get("event"), expected.get("event"))
    _check_equal(checks, "payload.published", payload.get("published"), expected.get("published"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "print_call_count": print_domain.emit_job_submitted.call_count,
            "inventory_call_count": inventory_domain.emit_stock_changed.call_count,
        },
    )


def _run_system_maintenance_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.routes import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "set_default_printer").strip().lower()
    body = dict(task.get("body") or {})
    method = "POST"
    path = "/api/system/printer"
    if action == "set_default_printer":
        body.setdefault("printer_name", "HP")
    elif action == "enable_startup":
        path = "/api/system/startup"
    elif action == "disable_startup":
        method = "DELETE"
        path = "/api/system/startup"
    elif action == "backup_database":
        path = "/api/database/backup"
    elif action == "delete_database_backup":
        method = "DELETE"
        backup_file = str(body.get("backup_file") or "backup.sql")
        body["backup_file"] = backup_file
        path = f"/api/database/backup/{backup_file}"
    elif action == "restore_database":
        path = "/api/database/restore"
        body.setdefault("backup_file", "backup.sql")
    elif action == "clear_performance_cache":
        path = "/api/performance/cache/clear?pattern=test:*"
        body.setdefault("pattern", "test:*")
    elif action == "invalidate_performance_cache":
        path = "/api/performance/cache/invalidate"
        body.setdefault("keys", ["k1"])
    elif action == "reinitialize_performance":
        path = "/api/performance/optimize/reinitialize"

    repo = InMemoryAgentRunRepository()
    system_service = Mock()
    system_service.set_default_printer.return_value = {"success": True, "message": "ok"}
    system_service.enable_startup.return_value = {"success": True, "message": "enabled"}
    system_service.disable_startup.return_value = {"success": True, "message": "disabled"}
    database_service = Mock()
    database_service.backup_database.return_value = {
        "success": True,
        "message": "backed up",
        "backup_file": "backup.sql",
    }
    database_service.delete_backup.return_value = {
        "success": True,
        "message": "deleted",
        "backup_file": "backup.sql",
    }
    database_service.restore_database.return_value = {
        "success": True,
        "message": "restored",
        "backup_file": "backup.sql",
    }
    optimizer = Mock()
    optimizer.redis_cache.clear_pattern.return_value = 5
    optimizer.redis_cache.clear_local_cache.return_value = None
    optimizer.redis_cache.delete.return_value = 1
    optimizer.get_status.return_value = {"status": "ok"}
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.facades.session_facade.get_system_service",
                    return_value=system_service,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.facades.session_facade.get_database_service",
                    return_value=database_service,
                )
            )
            stack.enter_context(
                patch("app.utils.performance_initializer.get_performance_optimizer", return_value=optimizer)
            )
            stack.enter_context(
                patch(
                    "app.utils.performance_initializer.init_performance_optimization",
                    return_value=optimizer,
                )
            )
            if method == "DELETE":
                response = client.delete(
                    path,
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )
            else:
                response = client.post(
                    path,
                    json=body,
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_dataset_rag_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.knowledge_v1 import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "query").strip().lower()
    body = dict(task.get("body") or {})
    method = "POST"
    path = "/api/knowledge/v1/datasets/platform-docs/query"
    if action == "query":
        body.setdefault("query", "Which model should AI routes use?")
        body.setdefault("tenant_id", "tenant-a")
        body.setdefault("include_answer", True)
    elif action == "ingest_document":
        path = "/api/knowledge/v1/datasets/platform-docs/documents"
        body.setdefault("source", "policy.pdf")
        body.setdefault("text", "AI routes should use AgentOrchestrator.")
        body.setdefault("tenant_id", "tenant-a")
    elif action == "diff_versions":
        path = "/api/knowledge/v1/datasets/platform-docs/versions/diff"
        body.setdefault("source", "policy.pdf")
        body.setdefault("tenant_id", "tenant-a")
        body.setdefault("from_version", "v1")
        body.setdefault("to_version", "latest")
    elif action == "rollback_version":
        path = "/api/knowledge/v1/datasets/platform-docs/versions/rollback"
        body.setdefault("source", "policy.pdf")
        body.setdefault("tenant_id", "tenant-a")
        body.setdefault("target_version", "v1")
    elif action == "rebuild_index":
        path = "/api/knowledge/v1/datasets/platform-docs/index/rebuild"
        body.setdefault("tenant_id", "tenant-a")
        body.setdefault("background", True)
    elif action == "cancel_rebuild":
        path = "/api/knowledge/v1/datasets/platform-docs/index/rebuild/rag_rebuild_1/cancel"
    elif action == "delete_document":
        method = "DELETE"
        path = "/api/knowledge/v1/datasets/platform-docs/documents/doc_1"

    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.answer.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "query": str(body.get("query") or ""),
        "answer": "AI routes should use AgentOrchestrator [1].",
        "chunks": [{"text": "AI routes should use AgentOrchestrator.", "source": "policy.pdf"}],
        "citations": [{"index": 1, "source": "policy.pdf"}],
    }
    service.ingest_document.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document": {"document_id": "doc_1", "source": "policy.pdf"},
        "chunk_count": 1,
    }
    service.diff_versions.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "source": "policy.pdf",
        "changed": True,
        "diff": ["--- v1", "+++ v2"],
    }
    service.rollback_document_version.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document": {"document_id": "doc_rollback"},
        "chunk_count": 1,
        "rolled_back_from": {"document_id": "doc_1", "version": 1},
    }
    service.start_rebuild_index.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "job": {"job_id": "rag_rebuild_1", "status": "queued"},
        "background": True,
    }
    service.cancel_rebuild_job.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "job_id": "rag_rebuild_1",
        "job": {"job_id": "rag_rebuild_1", "status": "cancelled"},
    }
    service.delete_document.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document_id": "doc_1",
        "deleted_chunks": 1,
    }
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        headers = {
            "X-User-Id": str(task.get("user_id") or "eval-user"),
            "X-Dataset-Tenant-ID": str(task.get("tenant_id") or "tenant-a"),
            "X-Dataset-Permissions": "dataset.read,dataset.write",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                    return_value=service,
                )
            )
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_memory_v2_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.misc.routes import router
    from app.services import user_memory_service as memory_mod

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "propose_candidate").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or body.get("user_id") or "eval-memory-user")
    method = "POST"
    path = "/memory/v2/candidates"

    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        tmp_path = Path(tmp_dir)
        memory_dir = tmp_path / "memory"
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(tmp_path / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(patch.object(memory_mod, "MEMORY_DIR", str(memory_dir)))
            stack.enter_context(
                patch.object(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
            )
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            memory_mod.reset_user_memory_service()
            try:
                if action == "propose_candidate":
                    body.setdefault("user_id", user_id)
                    body.setdefault("memory_type", "preference")
                    body.setdefault("key", "favorite_customer")
                    body.setdefault("value", "ACME Trading")
                    body.setdefault("source", "settings_ui")
                    body.setdefault("confidence", 0.9)
                else:
                    service = memory_mod.get_user_memory_service()
                    seed = service.propose_memory_candidate(
                        user_id,
                        "preference",
                        "favorite_customer",
                        "ACME Trading",
                        source="settings_ui",
                        confidence=0.9,
                    )
                    memory_id = str((seed.get("candidate") or {}).get("memory_id") or "")
                    if action in {"correct", "delete"}:
                        service.confirm_memory_candidate(user_id, memory_id)
                    body.setdefault("user_id", user_id)
                    if action == "confirm":
                        path = f"/memory/v2/{memory_id}/confirm"
                    elif action == "reject":
                        path = f"/memory/v2/{memory_id}/reject"
                        body.setdefault("reason", "not useful")
                    elif action == "correct":
                        method = "PATCH"
                        path = f"/memory/v2/{memory_id}"
                        body.setdefault("value", "ACME Trading Ltd.")
                        body.setdefault("reason", "user corrected value")
                    elif action == "delete":
                        method = "DELETE"
                        path = f"/memory/v2/{memory_id}"
                    else:
                        path = f"/memory/v2/{memory_id}/confirm"

                headers = {"X-User-Id": user_id}
                if method == "DELETE":
                    response = client.delete(
                        path,
                        params={
                            "user_id": user_id,
                            "reason": str(body.get("reason") or "user removed memory"),
                        },
                        headers=headers,
                    )
                elif method == "PATCH":
                    response = client.patch(path, json=body, headers=headers)
                else:
                    response = client.post(path, json=body, headers=headers)
            finally:
                memory_mod.reset_user_memory_service()

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    memory_payload = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    candidate_payload = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "payload.memory_status",
        memory_payload.get("status") or candidate_payload.get("status"),
        expected.get("memory_status"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_materials_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import materials as materials_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-materials-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_material.return_value = {"success": True, "data": {"id": 1, "name": "树脂"}}
    service.update_material.return_value = {"success": True, "data": {"id": 1}}
    service.delete_material.return_value = None
    service.batch_delete_materials.return_value = None

    app = FastAPI()
    app.include_router(materials_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    method = "POST"
    path = "/api/materials"
    if action == "create":
        body.setdefault("name", "树脂")
        body.setdefault("material_code", "R-001")
    elif action == "update":
        method = "PUT"
        path = f"/api/materials/{int(task.get('material_id') or 1)}"
        body.setdefault("name", "树脂 v2")
    elif action == "delete":
        method = "DELETE"
        path = f"/api/materials/{int(task.get('material_id') or 1)}"
    elif action == "batch_delete":
        path = "/api/materials/batch-delete"
        body.setdefault("ids", [1, 2])
    else:
        return _failed(task, f"unsupported materials route action: {action}")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch.object(
                    materials_routes,
                    "get_material_application_service",
                    lambda: service,
                )
            )
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "payload.deleted_count",
        payload.get("deleted_count"),
        expected.get("deleted_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create": service.create_material.call_count,
                "update": service.update_material.call_count,
                "delete": service.delete_material.call_count,
                "batch_delete": service.batch_delete_materials.call_count,
            },
        },
    )


def _run_inventory_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import inventory as inventory_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "stock_in").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-inventory-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_storage_location.return_value = {"success": True, "id": 11}
    service.update_storage_location.return_value = {"success": True, "data": {"id": 11}}
    service.create_warehouse.return_value = {"success": True, "data": {"id": 1}}
    service.update_warehouse.return_value = {"success": True, "data": {"id": 1}}
    service.delete_warehouse.return_value = {"success": True}
    service.inventory_in.return_value = {"success": True, "data": {"transaction_type": "in"}}
    service.inventory_out.return_value = {"success": True, "data": {"transaction_type": "out"}}
    service.inventory_transfer.return_value = {
        "success": True,
        "data": {"transaction_type": "transfer"},
    }

    method = "POST"
    path = "/api/inventory/in"
    if action == "create_storage_location":
        path = "/api/inventory/locations"
        body.setdefault("code", "A-01")
    elif action == "update_storage_location":
        method = "PUT"
        path = f"/api/inventory/locations/{int(task.get('location_id') or 11)}"
        body.setdefault("status", "full")
    elif action == "create_warehouse":
        path = "/api/inventory/warehouses"
        body.setdefault("name", "主仓")
    elif action == "update_warehouse":
        method = "PUT"
        path = f"/api/inventory/warehouses/{int(task.get('warehouse_id') or 1)}"
        body.setdefault("name", "副仓")
    elif action == "delete_warehouse":
        method = "DELETE"
        path = f"/api/inventory/warehouses/{int(task.get('warehouse_id') or 1)}"
    elif action == "stock_in":
        path = "/api/inventory/in"
        body.setdefault("product_id", 1)
        body.setdefault("warehouse_id", 2)
        body.setdefault("quantity", 3)
    elif action == "stock_out":
        path = "/api/inventory/out"
        body.setdefault("product_id", 1)
        body.setdefault("warehouse_id", 2)
        body.setdefault("quantity", 1)
    elif action == "transfer":
        path = "/api/inventory/transfer"
        body.setdefault("product_id", 1)
        body.setdefault("from_warehouse_id", 1)
        body.setdefault("to_warehouse_id", 2)
        body.setdefault("quantity", 1)
    else:
        return _failed(task, f"unsupported inventory route action: {action}")

    app = FastAPI()
    app.include_router(inventory_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(inventory_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_storage_location": service.create_storage_location.call_count,
                "update_storage_location": service.update_storage_location.call_count,
                "create_warehouse": service.create_warehouse.call_count,
                "update_warehouse": service.update_warehouse.call_count,
                "delete_warehouse": service.delete_warehouse.call_count,
                "inventory_in": service.inventory_in.call_count,
                "inventory_out": service.inventory_out.call_count,
                "inventory_transfer": service.inventory_transfer.call_count,
            },
        },
    )


def _run_purchase_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import purchase as purchase_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create_order").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-purchase-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_supplier.return_value = {"success": True, "data": {"id": 7}}
    service.update_supplier.return_value = {"success": True, "data": {"id": 7}}
    service.delete_supplier.return_value = {"success": True}
    service.create_purchase_order.return_value = {"success": True, "data": {"id": 9}}
    service.update_purchase_order.return_value = {"success": True, "data": {"id": 9}}
    service.approve_purchase_order.return_value = {
        "success": True,
        "data": {"status": "approved"},
    }
    service.cancel_purchase_order.return_value = {
        "success": True,
        "data": {"status": "cancelled"},
    }
    service.create_purchase_inbound.return_value = {"success": True, "data": {"id": 5}}

    method = "POST"
    path = "/api/purchase/orders"
    if action == "create_supplier":
        path = "/api/purchase/suppliers"
        body.setdefault("name", "星光供应商")
    elif action == "update_supplier":
        method = "PUT"
        path = f"/api/purchase/suppliers/{int(task.get('supplier_id') or 7)}"
        body.setdefault("status", "active")
    elif action == "delete_supplier":
        method = "DELETE"
        path = f"/api/purchase/suppliers/{int(task.get('supplier_id') or 7)}"
    elif action == "create_order":
        path = "/api/purchase/orders"
        body.setdefault("supplier_id", 7)
    elif action == "update_order":
        method = "PUT"
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}"
        body.setdefault("remark", "调整交期")
    elif action == "approve_order":
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}/approve"
    elif action == "cancel_order":
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}/cancel"
    elif action == "create_inbound":
        path = "/api/purchase/inbounds"
        body.setdefault("order_id", 9)
    else:
        return _failed(task, f"unsupported purchase route action: {action}")

    app = FastAPI()
    app.include_router(purchase_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(purchase_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                params = {"approver": str(task.get("approver") or "manager")}
                if action == "approve_order":
                    response = client.post(path, params=params, headers=headers)
                else:
                    response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_supplier": service.create_supplier.call_count,
                "update_supplier": service.update_supplier.call_count,
                "delete_supplier": service.delete_supplier.call_count,
                "create_purchase_order": service.create_purchase_order.call_count,
                "update_purchase_order": service.update_purchase_order.call_count,
                "approve_purchase_order": service.approve_purchase_order.call_count,
                "cancel_purchase_order": service.cancel_purchase_order.call_count,
                "create_purchase_inbound": service.create_purchase_inbound.call_count,
            },
        },
    )


def _run_finance_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import finance as finance_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create_transaction").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-finance-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_transaction.return_value = {
        "success": True,
        "data": {"id": 31, "transaction_type": "expense"},
    }
    service.update_transaction.return_value = {"success": True, "data": {"id": 31}}
    service.delete_transaction.return_value = {"success": True, "message": "凭证已删除"}

    method = "POST"
    path = "/api/finance/transactions"
    if action == "create_transaction":
        path = "/api/finance/transactions"
        body.setdefault("transaction_type", "expense")
        body.setdefault("amount", 128.5)
    elif action == "update_transaction":
        method = "PUT"
        path = f"/api/finance/transactions/{int(task.get('transaction_id') or 31)}"
        body.setdefault("status", "paid")
    elif action == "delete_transaction":
        method = "DELETE"
        path = f"/api/finance/transactions/{int(task.get('transaction_id') or 31)}"
    else:
        return _failed(task, f"unsupported finance route action: {action}")

    app = FastAPI()
    app.include_router(finance_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(finance_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_transaction": service.create_transaction.call_count,
                "update_transaction": service.update_transaction.call_count,
                "delete_transaction": service.delete_transaction.call_count,
            },
        },
    )


def _run_products_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.product import routes as product_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "batch_create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-products-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.batch_add_products.return_value = {"success": True, "data": {"success_count": 1}}
    service.update_product.return_value = {"success": True, "data": {"id": 7}}
    service.delete_product.return_value = {"success": True, "message": "产品删除成功"}

    method = "POST"
    path = "/api/products/batch"
    if action == "batch_create":
        path = "/api/products/batch"
        body.setdefault("products", [{"name": "5003", "unit_price": 12.5}])
    elif action == "update":
        method = "PUT"
        path = f"/api/products/{int(task.get('product_id') or 7)}"
        body.setdefault("name", "5003 v2")
    elif action == "delete":
        method = "DELETE"
        path = f"/api/products/{int(task.get('product_id') or 7)}"
    else:
        return _failed(task, f"unsupported products route action: {action}")

    app = FastAPI()
    app.include_router(product_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(product_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "batch_add_products": service.batch_add_products.call_count,
                "update_product": service.update_product.call_count,
                "delete_product": service.delete_product.call_count,
            },
        },
    )


def _run_products_compat_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.application.excel_imports as excel_imports
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.product import compat_routes as product_compat_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-products-compat-user")
    repo = InMemoryAgentRunRepository()

    path = "/products/add"
    if action == "create":
        path = "/products/add"
        body.setdefault("product_name", "5003")
        body.setdefault("unit", "个")
    elif action == "update":
        path = "/products/update"
        body.setdefault("id", 7)
        body.setdefault("name", "5003 v2")
    elif action == "delete":
        path = "/products/delete"
        body.setdefault("id", 7)
    elif action == "batch_delete":
        path = "/products/batch-delete"
        body.setdefault("ids", [7, 8])
    else:
        return _failed(task, f"unsupported products compat route action: {action}")

    app = FastAPI()
    app.include_router(product_compat_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        excel_imports.__dict__["_parse_price"] = lambda value: 0.0
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
                stack.enter_context(
                    patch(
                        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                        return_value=repo,
                    )
                )
                stack.enter_context(
                    patch(
                        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                        return_value=False,
                    )
                )
                stack.enter_context(
                    patch(
                        "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
                    )
                )
                stack.enter_context(
                    patch(
                        "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
                        return_value=None,
                    )
                )
                insert_row = stack.enter_context(
                    patch(
                        "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
                        return_value=7,
                    )
                )
                update_row = stack.enter_context(
                    patch("app.fastapi_routes.domains.product.compat_routes.products_pg_update_row")
                )
                delete_row = stack.enter_context(
                    patch("app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row")
                )
                batch_delete_rows = stack.enter_context(
                    patch(
                        "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
                        return_value=(2, []),
                    )
                )
                response = client.post(path, json=body, headers={"X-User-Id": user_id})
        finally:
            excel_imports.__dict__.pop("_parse_price", None)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "insert_row": insert_row.call_count,
                "update_row": update_row.call_count,
                "delete_row": delete_row.call_count,
                "batch_delete_rows": batch_delete_rows.call_count,
            },
        },
    )


def _run_customers_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.customer import routes as customer_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-customers-user")
    repo = InMemoryAgentRunRepository()
    deleted_ids: list[int] = []

    def _delete_customer(customer_id: int) -> None:
        deleted_ids.append(customer_id)

    method = "POST"
    path = "/customers"
    name = str(body.get("unit_name") or body.get("customer_name") or "星光贸易")
    contact_person = str(body.get("contact_person") or "张三")
    contact_phone = str(body.get("contact_phone") or "13900000000")
    contact_address = str(body.get("contact_address") or "上海")
    if action == "create":
        path = "/customers"
        body.setdefault("unit_name", name)
    elif action == "update":
        method = "PUT"
        path = f"/customers/{int(task.get('customer_id') or 7)}"
        body.setdefault("unit_name", name)
    elif action == "delete":
        method = "DELETE"
        path = f"/customers/{int(task.get('customer_id') or 7)}"
    elif action == "batch_delete":
        path = "/customers/batch-delete"
        body.setdefault("ids", [7, "bad", 8])
    else:
        return _failed(task, f"unsupported customers route action: {action}")

    app = FastAPI()
    app.include_router(customer_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
                    return_value=False,
                )
            )
            stack.enter_context(patch.object(customer_routes, "_customers_write_raise"))
            stack.enter_context(
                patch.object(
                    customer_routes,
                    "_customer_body_name_contact",
                    return_value=(name, contact_person, contact_phone, contact_address),
                )
            )
            insert_customer = stack.enter_context(
                patch.object(
                    customer_routes,
                    "_customer_pg_insert",
                    return_value={"id": 7, "unit_name": name},
                )
            )
            update_customer = stack.enter_context(
                patch.object(
                    customer_routes,
                    "_customer_pg_update",
                    return_value={"id": 7, "unit_name": name},
                )
            )
            stack.enter_context(
                patch.object(customer_routes, "_customer_delete_unified", side_effect=_delete_customer)
            )
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "customer_pg_insert": insert_customer.call_count,
                "customer_pg_update": update_customer.call_count,
                "customer_delete_unified": len(deleted_ids),
            },
        },
    )


def _run_shipment_records_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import shipment_orders

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-shipment-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_shipment.return_value = {"success": True, "data": {"id": 7}}
    service.update_shipment_record.return_value = {"success": True, "data": {"id": 7}}
    service.delete_shipment_record.return_value = {"success": True, "deleted_count": 1}

    method = "POST"
    path = "/api/shipment/shipment-records/record"
    if action == "create":
        body.setdefault("unit_name", "星光贸易")
        body.setdefault("products", [{"name": "5003", "qty": 2}])
    elif action == "update":
        method = "PATCH"
        body.setdefault("id", int(task.get("record_id") or 7))
        body.setdefault("status", "printed")
    elif action == "delete":
        method = "DELETE"
        body.setdefault("id", int(task.get("record_id") or 7))
    else:
        return _failed(task, f"unsupported shipment records route action: {action}")

    app = FastAPI()
    app.include_router(shipment_orders.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(shipment_orders, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.request("DELETE", path, json=body, headers=headers)
            elif method == "PATCH":
                response = client.patch(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_shipment": service.create_shipment.call_count,
                "update_shipment_record": service.update_shipment_record.call_count,
                "delete_shipment_record": service.delete_shipment_record.call_count,
            },
        },
    )


def _run_shipment_orders_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import shipment_orders

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "generate").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-shipment-order-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()

    method = "POST"
    path = "/api/shipment/generate"
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        shipment_file = Path(tmp_dir) / "shipment.xlsx"
        shipment_file.write_bytes(b"fake")
        service.generate_shipment_document.return_value = {
            "success": True,
            "file_path": str(shipment_file),
            "record_id": 7,
        }
        service.mark_as_printed.return_value = {"success": True, "message": "已标记为已打印"}
        service.clear_shipment_by_unit.return_value = {"success": True, "cleared_count": 2}
        service.set_order_sequence.return_value = {"success": True, "sequence": 12}
        service.reset_order_sequence.return_value = {"success": True, "sequence": 1}
        service.clear_all_orders.return_value = {"success": True, "deleted_count": 5}
        service.delete_shipment.return_value = {"success": True}

        if action == "generate":
            path = "/api/shipment/generate"
            body.setdefault("unit_name", "星光贸易")
            body.setdefault("products", [{"name": "5003", "qty": 2}])
        elif action == "generate_batch":
            path = "/api/shipment/generate-batch"
            body.setdefault(
                "shipments",
                [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}],
            )
        elif action == "print":
            path = "/api/shipment/print"
            body.setdefault("file_path", str(shipment_file))
            body.setdefault("order_id", 7)
            body.setdefault("printer_name", "HP")
        elif action == "clear_shipment":
            path = str(task.get("route_path") or "/api/shipment/orders/clear-shipment")
            body.setdefault("purchase_unit", "星光贸易")
        elif action == "set_sequence":
            path = str(task.get("route_path") or "/api/orders/set-sequence")
            body.setdefault("sequence", 12)
        elif action == "reset_sequence":
            path = str(task.get("route_path") or "/api/shipment/orders/reset-sequence")
        elif action == "clear_all":
            method = "DELETE"
            path = str(task.get("route_path") or "/api/orders/clear-all")
        elif action == "delete":
            method = "DELETE"
            path = str(task.get("route_path") or "/api/shipment/orders/7")
        else:
            return _failed(task, f"unsupported shipment orders route action: {action}")

        app = FastAPI()
        app.include_router(shipment_orders.router)
        client = TestClient(app, raise_server_exceptions=False)

        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(shipment_orders, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            response = client.request(method, path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "generate_shipment_document": service.generate_shipment_document.call_count,
                "mark_as_printed": service.mark_as_printed.call_count,
                "clear_shipment_by_unit": service.clear_shipment_by_unit.call_count,
                "set_order_sequence": service.set_order_sequence.call_count,
                "reset_order_sequence": service.reset_order_sequence.call_count,
                "clear_all_orders": service.clear_all_orders.call_count,
                "delete_shipment": service.delete_shipment.call_count,
            },
        },
    )


def _run_print_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import print_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "print_document").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-print-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    method = "POST"
    path = "/api/print/document"

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        document_file = Path(tmp_dir) / "document.pdf"
        document_file.write_bytes(b"%PDF")
        label_file = Path(tmp_dir) / "label.png"
        label_file.write_bytes(b"\x89PNG\r\n")
        service.get_printers.return_value = {
            "success": True,
            "printers": [{"name": "DocPrinter"}, {"name": "LabelPrinter"}],
        }
        service.save_printer_selection.return_value = {
            "success": True,
            "message": "打印机选择已保存",
        }
        service.classify_printers.return_value = {
            "document": ["DocPrinter"],
            "label": ["LabelPrinter"],
        }
        service.print_document.return_value = {"success": True, "message": "文档已提交打印"}
        service.print_label.return_value = {"success": True, "message": "标签已打印"}
        service.test_printer.return_value = {"success": True, "message": "测试页已发送"}
        print_app = Mock()
        print_app.print_single_label.return_value = {
            "success": True,
            "message": "标签已打印",
            "model_number": "M-1",
            "quantity": 2,
        }
        product_service = Mock()
        product_service.search_products.return_value = [
            {"name": "产品M1", "specification": "红色", "unit": "盒"}
        ]

        if action == "save_printer_selection":
            method = "PUT"
            path = "/api/print/printer-selection"
            body.setdefault("document_printer", "DocPrinter")
            body.setdefault("label_printer", "LabelPrinter")
        elif action == "print_document":
            path = "/api/print/document"
            body.setdefault("file_path", str(document_file))
            body.setdefault("printer_name", "DocPrinter")
            body.setdefault("use_automation", False)
        elif action == "print_label":
            path = "/api/print/label"
            body.setdefault("file_path", str(label_file))
            body.setdefault("printer_name", "LabelPrinter")
            body.setdefault("copies", 2)
            body.setdefault("require_confirm", False)
        elif action == "test":
            path = "/api/print/test"
            body.setdefault("printer_name", "DocPrinter")
        elif action == "workflow_label_dispatch":
            path = "/api/print/workflow/label-print/dispatch"
            body.setdefault("model_number", "M-1")
            body.setdefault("quantity", 2)
            body.setdefault("idempotency_key", "idem-eval")
        else:
            return _failed(task, f"unsupported print route action: {action}")

        app = FastAPI()
        app.include_router(print_routes.router)
        client = TestClient(app, raise_server_exceptions=False)

        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(print_routes, "_svc", lambda: service))
            stack.enter_context(
                patch(
                    "app.application.print_app_service.get_print_application_service",
                    return_value=print_app,
                )
            )
            stack.enter_context(
                patch("app.application.get_product_app_service", return_value=product_service)
            )
            headers = {"X-User-Id": user_id}
            response = client.request(method, path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "get_printers": service.get_printers.call_count,
                "save_printer_selection": service.save_printer_selection.call_count,
                "print_document": service.print_document.call_count,
                "print_label": service.print_label.call_count,
                "test_printer": service.test_printer.call_count,
                "print_single_label": print_app.print_single_label.call_count,
                "product_search": product_service.search_products.call_count,
            },
        },
    )


def _run_tools_execute_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = bool(task.get("mock_publish_result", True))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain)
            )
            response = client.post(
                str(task.get("path") or "/api/tools/execute"),
                json=dict(
                    task.get("body")
                    or {
                        "tool_id": "ocr",
                        "action": "request",
                        "params": {
                            "request_id": "tools-ocr-eval",
                            "image_url": "https://example.invalid/label.png",
                            "ocr_type": "invoice",
                            "user_id": str(task.get("user_id") or "eval-user"),
                        },
                    }
                ),
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "publish_call_count": ocr_domain.emit_ocr_requested.call_count,
        },
    )


def _run_templates_analyze_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    filename = str(task.get("filename") or "shipment-template.xlsx")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_structured_excel_preview",
                    return_value=dict(
                        task.get("mock_structured_result")
                        or {
                            "fields": [{"label": "客户", "type": "dynamic"}],
                            "sample_rows": [{"客户": "ACME Trading"}],
                        }
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_grid_preview",
                    return_value=dict(
                        task.get("mock_grid_preview")
                        or {"rows": [["客户"], ["ACME Trading"]]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_grid_style_cache",
                    return_value=dict(task.get("mock_style_cache") or {"cells": {}}),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_all_sheets_preview",
                    return_value=list(task.get("mock_sheets") or [{"sheet_name": "出货"}]),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._list_excel_sheet_names",
                    return_value=list(task.get("mock_sheet_names") or ["出货"]),
                )
            )
            response = client.post(
                "/api/templates/analyze",
                files={
                    "file": (
                        filename,
                        bytes(str(task.get("file_body") or "eval-template"), "utf-8"),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data=dict(
                    task.get("form")
                    or {"template_name": "发货模板", "template_scope": "shipment"}
                ),
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks,
            "artifact_count",
            len(run.artifacts),
            expected.get("artifact_count"),
            skip_when_expected_missing=True,
        )
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_excel_skill_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openpyxl import Workbook

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.excel.routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    route_path = str(task.get("path") or "/api/skills/analyze/excel")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        xlsx_path = Path(tmp_dir) / str(task.get("filename") or "excel-skill-route.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = str(task.get("sheet_name") or "Sheet1")
        ws.append(["客户", "数量"])
        ws.append(["ACME Trading", 3])
        wb.save(xlsx_path)

        body = dict(task.get("body") or {})
        body.setdefault("file_path", str(xlsx_path))
        body.setdefault("sheet_name", ws.title)

        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with (
            patch.dict(os.environ, env_patch, clear=False),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            response = client.post(
                route_path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_label_template_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.excel.routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        body = dict(
            task.get("body")
            or {
                "image_path": "/tmp/label.png",
                "class_name": "ProductLabelTemplate",
                "enable_ocr": True,
            }
        )
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.analyze_image",
                    return_value=dict(
                        task.get("mock_analysis")
                        or {"success": True, "file": "label.png", "size": [800, 600]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
                    return_value=dict(
                        task.get("mock_ocr_result")
                        or {"success": True, "fields": [{"label": "品名", "value": "清漆"}]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
                    return_value=str(
                        task.get("mock_code") or "class ProductLabelTemplate:\n    pass\n"
                    ),
                )
            )
            response = client.post(
                "/api/skills/generate-label-template",
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_document_template_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.routes import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower() or "create"
    if action == "update":
        path = "/api/templates/update"
    elif action == "delete":
        path = "/api/templates/delete"
    else:
        path = "/api/templates/create"
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        body = dict(task.get("body") or {})
        if action == "update":
            body.setdefault("id", "db:1")
            body.setdefault("name", "发货模板 v2")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板更新成功",
                    "template": {"id": "db:1", "db_id": 1, "name": body.get("name")},
                }
            )
            patch_target = "app.fastapi_routes.document_templates_compat.run_archive_template_update"
        elif action == "delete":
            body.setdefault("id", "db:1")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板删除成功",
                    "deleted": {"id": body.get("id"), "db_id": 1},
                }
            )
            patch_target = "app.fastapi_routes.document_templates_compat.run_archive_template_delete"
        else:
            body.setdefault("name", "发货模板")
            body.setdefault("template_type", "Excel")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板创建成功",
                    "template": {"id": "db:1", "db_id": 1, "name": body.get("name")},
                }
            )
            patch_target = "app.fastapi_routes.document_templates_compat.run_archive_template_create"
        mocked_status = int(task.get("mock_status_code") or 200)
        with (
            patch.dict(os.environ, env_patch, clear=False),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
            patch(patch_target, return_value=(mocked_response, mocked_status)),
        ):
            response = client.post(
                path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count"))
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _inject_file_analysis_path(payload: dict[str, Any], file_path: Path, source: str) -> None:
    data = payload.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        payload["data"] = data
    analysis = data.setdefault("file_analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}
        data["file_analysis"] = analysis
    analysis["file_path"] = str(file_path)
    analysis.setdefault("saved_name", source)
    analysis.setdefault("filename", source)


def _run_agent_run_memory_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    payload = dict(task.get("payload") or {})
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message=str(task.get("message") or task.get("id") or ""),
            runtime_context={"source": "agent_eval", "task_id": str(task.get("id") or "")},
            user_id="eval-user",
            source="agent_eval",
            channel="eval_chat",
        )

    run = repo.get(str(result.get("run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "run_attached", run is not None, True)
    if run is None:
        return _result(task, checks, {"payload": result})

    _check_equal(
        checks,
        "memory_reference_count",
        len(run.memory_references),
        expected.get("memory_reference_count"),
    )
    _check_equal(
        checks,
        "memory_hit_count",
        run.metadata.get("memory_hit_count"),
        expected.get("memory_hit_count"),
    )
    if run.memory_references:
        reference = run.memory_references[0]
        for key in ("query", "memory_type", "source", "status"):
            if key in expected:
                _check_equal(
                    checks,
                    f"memory_references[0].{key}",
                    getattr(reference, key),
                    expected.get(key),
                )
        if "first_hit_chunk_id" in expected:
            first_chunk_id = str((reference.hits[0] if reference.hits else {}).get("chunk_id") or "")
            _check_equal(
                checks,
                "memory_references[0].hits[0].chunk_id",
                first_chunk_id,
                expected.get("first_hit_chunk_id"),
            )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(task, checks, {"run": run.to_dict(), "payload": result})


def _run_memory_v2_lifecycle_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.services import user_memory_service as memory_module
    from app.services.user_memory_service import UserMemoryService, reset_user_memory_service

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    user_id = str(task.get("user_id") or "eval-user")
    key = str(task.get("key") or "favorite_customer")
    value = task.get("value")
    corrected_value = task.get("corrected_value", value)
    entity_key = str(task.get("entity_key") or "customer_alias:acme")
    entity_value = task.get("entity_value", corrected_value)

    with tempfile.TemporaryDirectory() as tmp_dir:
        memory_path = Path(tmp_dir) / "memory_store.json"
        with (
            patch.object(memory_module, "MEMORY_DIR", tmp_dir),
            patch.object(memory_module, "JSON_MEMORY_PATH", str(memory_path)),
        ):
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None
            svc = UserMemoryService(storage_type="json")

            proposed = svc.propose_memory_candidate(
                user_id,
                "preference",
                key,
                value,
                confidence=float(task.get("confidence") or 0.8),
                evidence=[{"source": "agent_eval"}],
            )
            duplicate = svc.propose_memory_candidate(user_id, "preference", key, value)
            preference_before = svc.get_preference(user_id, key)
            candidate = dict(proposed.get("candidate") or {})
            confirmed = svc.confirm_memory_candidate(user_id, str(candidate.get("memory_id") or ""))
            corrected = svc.correct_memory(
                user_id,
                str(candidate.get("memory_id") or ""),
                value=corrected_value,
                reason="eval correction",
            )

            entity = svc.propose_memory_candidate(user_id, "entity", entity_key, entity_value)
            entity_candidate = dict(entity.get("candidate") or {})
            svc.confirm_memory_candidate(user_id, str(entity_candidate.get("memory_id") or ""))
            deleted = svc.delete_memory(
                user_id,
                str(entity_candidate.get("memory_id") or ""),
                reason="eval cleanup",
            )

            summary = svc.get_memory_v2_summary(user_id)
            memory_summary = svc.get_memory_summary(user_id)
            active_records = svc.list_memories(user_id, status="active")
            deleted_records = svc.list_memories(user_id, status="deleted")
            preference_after_correct = svc.get_preference(user_id, key)
            persisted = memory_path.exists()

            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None

    _check_equal(checks, "candidate_created", proposed.get("created"), True)
    _check_equal(checks, "duplicate_created", duplicate.get("created"), False)
    _check_equal(checks, "preference_before_confirmation", preference_before, None)
    _check_equal(
        checks,
        "confirmed_status",
        dict(confirmed.get("memory") or {}).get("status"),
        "active",
    )
    _check_equal(
        checks,
        "corrected_value",
        dict(corrected.get("memory") or {}).get("value"),
        corrected_value,
    )
    _check_equal(checks, "preference_after_correct", preference_after_correct, corrected_value)
    _check_equal(checks, "deleted_status", dict(deleted.get("memory") or {}).get("status"), "deleted")
    _check_equal(checks, "summary.total", summary.get("total"), expected.get("total"))
    _check_equal(
        checks,
        "summary.by_status.active",
        dict(summary.get("by_status") or {}).get("active"),
        expected.get("active_count"),
    )
    _check_equal(
        checks,
        "summary.by_status.deleted",
        dict(summary.get("by_status") or {}).get("deleted"),
        expected.get("deleted_count"),
    )
    _check_equal(
        checks,
        "summary.by_type.preference",
        dict(summary.get("by_type") or {}).get("preference"),
        expected.get("preference_count"),
    )
    _check_equal(
        checks,
        "summary.by_type.entity",
        dict(summary.get("by_type") or {}).get("entity"),
        expected.get("entity_count"),
    )
    _check_equal(
        checks,
        "memory_summary.memory_v2_active_count",
        memory_summary.get("memory_v2_active_count"),
        expected.get("active_count"),
    )
    _check_equal(checks, "active_records", len(active_records), expected.get("active_count"))
    _check_equal(checks, "deleted_records", len(deleted_records), expected.get("deleted_count"))
    _check_equal(checks, "persisted", persisted, True)
    return _result(
        task,
        checks,
        {
            "proposed": proposed,
            "duplicate": duplicate,
            "confirmed": confirmed,
            "corrected": corrected,
            "deleted": deleted,
            "summary": summary,
            "memory_summary": memory_summary,
        },
    )


def _run_memory_v2_planner_context_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
    from app.application.workflow.types import PlanGraph, WorkflowNode

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    active_summary = str(task.get("active_summary") or "")
    captured_context: dict[str, Any] = {}

    def fake_react(
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph:
        del user_id, message, tool_registry
        captured_context.update(dict(context or {}))
        return PlanGraph(
            plan_id=plan_id,
            intent="product_query",
            nodes=[
                WorkflowNode(
                    node_id="query_products",
                    tool_id="products",
                    action="query",
                    params={"keyword": "ACME 5003"},
                )
            ],
            metadata={
                "memory_v2_summary": dict(context.get("memory_v2") or {}).get("summary", ""),
            },
        )

    memory_service = SimpleNamespace(format_memory_v2_for_prompt=lambda **_: active_summary)
    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="full",
        ),
        patch("app.services.user_memory_service.get_user_memory_service", return_value=memory_service),
    ):
        planner = LLMWorkflowPlanner()
        with patch.object(planner, "_plan_with_react_multiagent", side_effect=fake_react):
            plan = planner.plan(
                str(task.get("user_id") or "eval-memory-user"),
                str(task.get("message") or "query product"),
                get_tool_registry(),
                {},
            )

    summary = str(dict(captured_context.get("memory_v2") or {}).get("summary") or "")
    _check_equal(checks, "context_has_memory_v2", bool(summary), True)
    _check_equal(checks, "plan_metadata_memory_v2", plan.metadata.get("memory_v2_summary"), summary)
    if expected.get("summary_contains"):
        fragment = str(expected.get("summary_contains") or "")
        checks.append(
            {
                "name": "summary_contains",
                "passed": fragment in summary,
                "actual": summary,
                "expected": fragment,
            }
        )
    if expected.get("summary_not_contains"):
        fragment = str(expected.get("summary_not_contains") or "")
        checks.append(
            {
                "name": "summary_not_contains",
                "passed": fragment not in summary,
                "actual": summary,
                "expected": f"not {fragment}",
            }
        )
    return _result(
        task,
        checks,
        {
            "captured_context": captured_context,
            "plan": {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "metadata": plan.metadata,
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "tool_id": node.tool_id,
                        "action": node.action,
                        "params": node.params,
                    }
                    for node in plan.nodes
                ],
            },
        },
    )


def _run_memory_v2_governance_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.services import user_memory_service as memory_module
    from app.services.user_memory_service import UserMemoryService, reset_user_memory_service

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    user_id = str(task.get("user_id") or "eval-memory-governance")

    with tempfile.TemporaryDirectory() as tmp_dir:
        memory_path = Path(tmp_dir) / "memory_store.json"
        with (
            patch.object(memory_module, "MEMORY_DIR", tmp_dir),
            patch.object(memory_module, "JSON_MEMORY_PATH", str(memory_path)),
        ):
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None
            svc = UserMemoryService(storage_type="json")

            trusted = svc.propose_memory_candidate(
                user_id,
                "preference",
                str(task.get("trusted_key") or "favorite_customer"),
                task.get("trusted_value") or "ACME Trading",
                source=str(task.get("trusted_source") or "settings_ui"),
                confidence=float(task.get("trusted_confidence") or 0.85),
            )
            trusted_id = str(dict(trusted.get("candidate") or {}).get("memory_id") or "")
            confirmed = svc.confirm_memory_candidate(user_id, trusted_id)

            blocked = svc.propose_memory_candidate(
                user_id,
                "preference",
                str(task.get("blocked_key") or "favorite_customer"),
                task.get("blocked_value") or "Poison Corp",
                source=str(task.get("blocked_source") or "llm_guess"),
                confidence=float(task.get("blocked_confidence") or 0.99),
            )
            blocked_candidate = dict(blocked.get("candidate") or {})
            blocked_confirm = svc.confirm_memory_candidate(
                user_id,
                str(blocked_candidate.get("memory_id") or ""),
            )

            unverified = svc.propose_memory_candidate(
                user_id,
                "entity",
                str(task.get("unverified_key") or "customer_alias:maybe"),
                task.get("unverified_value") or "Maybe Corp",
                source=str(task.get("unverified_source") or "unknown_scraper"),
                confidence=float(task.get("unverified_confidence") or 0.9),
            )
            summary = svc.get_memory_v2_summary(user_id)
            prompt_context = svc.format_memory_v2_for_prompt(user_id)
            active = svc.list_memories(user_id, status="active")
            rejected = svc.list_memories(user_id, status="rejected")
            pending = svc.list_memories(user_id, status="pending")
            preference_value = svc.get_preference(
                user_id,
                str(task.get("trusted_key") or "favorite_customer"),
            )
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None

    trusted_candidate = dict(trusted.get("candidate") or {})
    unverified_candidate = dict(unverified.get("candidate") or {})
    _check_equal(checks, "trusted.source_policy", trusted_candidate.get("source_policy"), "trusted_pending")
    _check_equal(checks, "trusted.confirmed_status", dict(confirmed.get("memory") or {}).get("status"), "active")
    _check_equal(checks, "blocked.status", blocked_candidate.get("status"), "rejected")
    _check_equal(checks, "blocked.source_policy", blocked_candidate.get("source_policy"), "blocked")
    _check_equal(checks, "blocked.confirm_success", blocked_confirm.get("success"), False)
    _check_equal(
        checks,
        "unverified.source_policy",
        unverified_candidate.get("source_policy"),
        "needs_evidence",
    )
    _check_equal(
        checks,
        "unverified.confidence_capped",
        unverified_candidate.get("confidence"),
        expected.get("unverified_confidence"),
    )
    _check_equal(checks, "summary.total", summary.get("total"), expected.get("total"))
    _check_equal(
        checks,
        "summary.by_status.active",
        dict(summary.get("by_status") or {}).get("active"),
        expected.get("active_count"),
    )
    _check_equal(
        checks,
        "summary.by_status.rejected",
        dict(summary.get("by_status") or {}).get("rejected"),
        expected.get("rejected_count"),
    )
    _check_equal(
        checks,
        "summary.by_status.pending",
        dict(summary.get("by_status") or {}).get("pending"),
        expected.get("pending_count"),
    )
    _check_equal(
        checks,
        "summary.by_source_policy.blocked",
        dict(summary.get("by_source_policy") or {}).get("blocked"),
        expected.get("blocked_count"),
    )
    _check_equal(
        checks,
        "summary.by_source_policy.needs_evidence",
        dict(summary.get("by_source_policy") or {}).get("needs_evidence"),
        expected.get("needs_evidence_count"),
    )
    _check_equal(checks, "active_records", len(active), expected.get("active_count"))
    _check_equal(checks, "rejected_records", len(rejected), expected.get("rejected_count"))
    _check_equal(checks, "pending_records", len(pending), expected.get("pending_count"))
    _check_equal(
        checks,
        "preference_value",
        preference_value,
        task.get("trusted_value") or "ACME Trading",
    )
    if expected.get("context_contains"):
        fragment = str(expected.get("context_contains") or "")
        checks.append(
            {
                "name": "context_contains",
                "passed": fragment in prompt_context,
                "actual": prompt_context,
                "expected": fragment,
            }
        )
    for fragment in list(expected.get("context_not_contains") or []):
        checks.append(
            {
                "name": f"context_not_contains:{fragment}",
                "passed": str(fragment) not in prompt_context,
                "actual": prompt_context,
                "expected": f"not {fragment}",
            }
        )
    return _result(
        task,
        checks,
        {
            "trusted": trusted,
            "confirmed": confirmed,
            "blocked": blocked,
            "blocked_confirm": blocked_confirm,
            "unverified": unverified,
            "summary": summary,
            "prompt_context": prompt_context,
        },
    )


def _build_plan(task: dict[str, Any]):
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan_data = dict(task.get("plan") or {})
    nodes = [
        WorkflowNode(
            node_id=str(node.get("node_id") or ""),
            tool_id=str(node.get("tool_id") or ""),
            action=str(node.get("action") or ""),
            params=dict(node.get("params") or {}),
            risk=node.get("risk") or "low",
            idempotent=bool(node.get("idempotent", False)),
            description=str(node.get("description") or ""),
            depends_on=list(node.get("depends_on") or []),
        )
        for node in list(plan_data.get("nodes") or [])
        if isinstance(node, dict)
    ]
    return PlanGraph(
        plan_id=str(plan_data.get("plan_id") or task.get("id") or ""),
        intent=str(plan_data.get("intent") or ""),
        todo_steps=list(plan_data.get("todo_steps") or []),
        nodes=nodes,
        risk_level=plan_data.get("risk_level") or "low",
        metadata=dict(plan_data.get("metadata") or {}),
    )


def _check_equal(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    expected: Any,
    *,
    skip_when_expected_missing: bool = False,
) -> None:
    if skip_when_expected_missing and expected is None:
        return
    checks.append(
        {
            "name": name,
            "passed": actual == expected,
            "actual": _json_safe(actual),
            "expected": _json_safe(expected),
        }
    )


def _check_tool_calls(checks: list[dict[str, Any]], tool_calls: list[Any], expected: list[dict[str, Any]]) -> None:
    for index, expected_call in enumerate(expected):
        actual_call = tool_calls[index] if index < len(tool_calls) else None
        for key, expected_value in expected_call.items():
            actual_value = getattr(actual_call, key, None) if actual_call is not None else None
            _check_equal(checks, f"tool_calls[{index}].{key}", actual_value, expected_value)


def _check_step_attempts(checks: list[dict[str, Any]], steps: list[Any], expected: list[int]) -> None:
    for index, expected_count in enumerate(expected):
        actual_step = steps[index] if index < len(steps) else None
        actual_value = getattr(actual_step, "attempt_count", None) if actual_step is not None else None
        _check_equal(checks, f"steps[{index}].attempt_count", actual_value, expected_count)


def _check_final_step_params(
    checks: list[dict[str, Any]],
    steps: list[Any],
    expected: dict[str, Any],
) -> None:
    for node_id, expected_params in expected.items():
        actual_step = next(
            (step for step in steps if str(getattr(step, "node_id", "")) == str(node_id)),
            None,
        )
        actual_params = dict(getattr(actual_step, "params", {}) or {}) if actual_step is not None else {}
        for key, expected_value in dict(expected_params or {}).items():
            _check_equal(
                checks,
                f"steps[{node_id}].params.{key}",
                actual_params.get(key),
                expected_value,
            )


def _check_final_node_outputs(
    checks: list[dict[str, Any]],
    final_output: dict[str, Any] | None,
    expected: dict[str, Any],
) -> None:
    if not expected:
        return
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    for node_id, expected_output in expected.items():
        actual_output = dict(node_outputs.get(str(node_id)) or {})
        for key, expected_value in dict(expected_output or {}).items():
            _check_equal(
                checks,
                f"final_output.node_outputs.{node_id}.{key}",
                actual_output.get(key),
                expected_value,
            )


def _check_event_types(checks: list[dict[str, Any]], events: list[Any], expected: list[str]) -> None:
    actual = [str(getattr(event, "event_type", "")) for event in events]
    for event_type in expected:
        checks.append(
            {
                "name": f"event_type:{event_type}",
                "passed": event_type in actual,
                "actual": actual,
                "expected": event_type,
            }
        )


def _check_step_errors(checks: list[dict[str, Any]], steps: list[Any], expected_fragments: list[str]) -> None:
    if not expected_fragments:
        return
    errors = [str(getattr(step, "error", "")) for step in steps]
    for fragment in expected_fragments:
        checks.append(
            {
                "name": f"step_error_contains:{fragment}",
                "passed": any(fragment in error for error in errors),
                "actual": errors,
                "expected": fragment,
            }
        )


def _result(task: dict[str, Any], checks: list[dict[str, Any]], details: dict[str, Any]) -> dict[str, Any]:
    failed_checks = [check for check in checks if not check["passed"]]
    return {
        "id": str(task.get("id") or ""),
        "kind": str(task.get("kind") or ""),
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "checks": checks,
        "details": _json_safe(details),
    }


def _failed(task: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or ""),
        "kind": str(task.get("kind") or ""),
        "passed": False,
        "failed_checks": [{"name": "task", "passed": False, "actual": message, "expected": "pass"}],
        "checks": [],
        "details": {},
    }


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except TypeError:
        return str(value)


@contextmanager
def _patched_llm_env(env: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in _LLM_ENV_KEYS}
    try:
        for key in _LLM_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in env.items():
            os.environ[str(key)] = str(value)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline agent platform eval tasks.")
    parser.add_argument(
        "--tasks",
        type=Path,
        default=DEFAULT_TASKS_PATH,
        help="Path to JSONL eval tasks.",
    )
    args = parser.parse_args(argv)
    result = run_eval(args.tasks)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
