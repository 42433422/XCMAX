# mypy: disable-error-code="arg-type, assignment, attr-defined, exit-return, operator, union-attr"
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
    # Offline parent-process mocks are contracts, not process/runtime acceptance.
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    class FixtureToolExecutor(AgentToolExecutor):
        def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
            return self.execute(step, runtime_context=runtime_context)

    with tempfile.TemporaryDirectory(prefix="xcagi-agent-eval-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        isolated_env = {
            "XCAGI_DATA_DIR": str(tmp_path / "xcagi-data"),
            "XCAGI_DESKTOP_DATA_DIR": str(tmp_path / "xcagi-data"),
            "DATASET_RAG_STORE_PATH": str(tmp_path / "dataset-rag" / "datasets.json"),
            "DATASET_RAG_VECTOR_INDEX_PATH": str(tmp_path / "dataset-rag" / "vectors.sqlite3"),
            "MODEL_USAGE_LEDGER_PATH": str(tmp_path / "model-usage.json"),
        }
        with (
            patch.dict(os.environ, isolated_env, clear=False),
            patch(
                "app.application.agent_orchestrator.orchestrator.AgentToolExecutor",
                FixtureToolExecutor,
            ),
        ):
            results = [run_task(task) for task in load_tasks(path)]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "suite": "agent_platform_minimum",
        "execution_mode": "fixture_local",
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
        dict(item) for item in list(task.get("mock_results") or []) if isinstance(item, dict)
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
                        "XCAUTO_API_KEY": "eval-xcauto-token",  # credential-guard: allow eval fixture
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
    _check_final_node_outputs(
        checks, run.final_output, dict(expected.get("final_node_outputs") or {})
    )
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
    from app.domain.conversation.legacy_services.api import ApiMixin

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
    def __init__(
        self, responses: list[_EvalMarketWalletResponse], calls: list[dict[str, Any]]
    ) -> None:
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
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
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
    document = (
        ingest_result.get("document") if isinstance(ingest_result.get("document"), dict) else {}
    )
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
                "passed": str(expected.get("answer_contains") or "")
                in str(answer_result.get("answer") or ""),
                "actual": answer_result.get("answer"),
                "expected": expected.get("answer_contains"),
            }
        )
    citations = (
        answer_result.get("citations") if isinstance(answer_result.get("citations"), list) else []
    )
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
                "passed": str(expected.get("reload_answer_contains") or "")
                in str(reload_answer_result.get("answer") or ""),
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
                "passed": len(reload_citations)
                >= int(expected.get("reload_citation_count_min") or 0),
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
                "passed": str(expected.get("latest_answer_contains") or "")
                in str(latest_answer.get("answer") or ""),
                "actual": latest_answer.get("answer"),
                "expected": expected.get("latest_answer_contains"),
            }
        )
    if "latest_answer_not_contains" in expected:
        checks.append(
            {
                "name": "latest_answer_not_contains",
                "passed": str(expected.get("latest_answer_not_contains") or "")
                not in str(latest_answer.get("answer") or ""),
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
    reload_index = (
        reload_status.get("index") if isinstance(reload_status.get("index"), dict) else {}
    )
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
                "passed": str(expected.get("reload_answer_contains") or "")
                in str(reload_answer.get("answer") or ""),
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
                "passed": str(expected.get("latest_after_rollback_contains") or "")
                in str(latest_answer.get("answer") or ""),
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
                "passed": str(expected.get("own_answer_contains") or "")
                in str(own_answer.get("answer") or ""),
                "actual": own_answer.get("answer"),
                "expected": expected.get("own_answer_contains"),
            }
        )
    if "own_answer_not_contains" in expected:
        checks.append(
            {
                "name": "own_answer_not_contains",
                "passed": str(expected.get("own_answer_not_contains") or "")
                not in str(own_answer.get("answer") or ""),
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
    _check_equal(
        checks, "first.job.queue_position", (first.get("job") or {}).get("queue_position"), 1
    )
    _check_equal(checks, "second.job.status", (second.get("job") or {}).get("status"), "queued")
    _check_equal(
        checks, "second.job.queue_position", (second.get("job") or {}).get("queue_position"), 2
    )
    queue = (
        queued_status.get("rebuild_queue")
        if isinstance(queued_status.get("rebuild_queue"), dict)
        else {}
    )
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
    final_queue = (
        final_status.get("rebuild_queue")
        if isinstance(final_status.get("rebuild_queue"), dict)
        else {}
    )
    _check_equal(
        checks,
        "final_queue.completed",
        final_queue.get("completed"),
        expected.get("completed_count"),
    )
    _check_equal(
        checks,
        "final_queue.cancelled",
        final_queue.get("cancelled"),
        expected.get("cancelled_count"),
    )
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
                "passed": str(expected.get("answer_contains") or "")
                in str(answer.get("answer") or ""),
                "actual": answer.get("answer"),
                "expected": expected.get("answer_contains"),
            }
        )
    if "answer_not_contains" in expected:
        checks.append(
            {
                "name": "answer_not_contains",
                "passed": str(expected.get("answer_not_contains") or "")
                not in str(answer.get("answer") or ""),
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
                "passed": str(expected.get("reload_answer_contains") or "")
                in str(reload_answer.get("answer") or ""),
                "actual": reload_answer.get("answer"),
                "expected": expected.get("reload_answer_contains"),
            }
        )
    reload_index = (
        reload_status.get("index") if isinstance(reload_status.get("index"), dict) else {}
    )
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
    return _result(
        task, checks, {"run": run.to_dict(), "payload": result, "market_calls": market_calls}
    )


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
    _check_equal(
        checks, "citation_count", run.metadata.get("citation_count"), expected.get("citation_count")
    )
    if run.retrieval_calls:
        call = run.retrieval_calls[0]
        for key in ("query", "retriever", "source", "top_k", "status"):
            if key in expected:
                _check_equal(
                    checks, f"retrieval_calls[0].{key}", getattr(call, key), expected.get(key)
                )
        if "first_citation_source" in expected:
            first_source = str((call.citations[0] if call.citations else {}).get("source") or "")
            _check_equal(
                checks,
                "retrieval_calls[0].citations[0].source",
                first_source,
                expected.get("first_citation_source"),
            )
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
                _check_equal(
                    checks, f"artifacts[0].{key}", getattr(artifact, key), expected.get(key)
                )
        if "first_field_name" in expected:
            first_field_name = str(
                (artifact.fields[0] if artifact.fields else {}).get("name") or ""
            )
            _check_equal(
                checks,
                "artifacts[0].fields[0].name",
                first_field_name,
                expected.get("first_field_name"),
            )
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
    ingests = [item for item in run.metadata.get("dataset_ingests", []) if isinstance(item, dict)]
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
                "passed": str(expected.get("dataset_answer_contains") or "")
                in str(answer_result.get("answer") or ""),
                "actual": answer_result.get("answer"),
                "expected": expected.get("dataset_answer_contains"),
            }
        )
    if "dataset_reload_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_reload_answer_contains",
                "passed": str(expected.get("dataset_reload_answer_contains") or "")
                in str(reload_answer_result.get("answer") or ""),
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
                        "app.domain.kitten_ai_document.generate.generate_office_file",
                        return_value=(content, file_name),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.domain.kitten_ai_document.pickup.store_document_pickup",
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
    _check_final_node_outputs(
        checks, run.final_output, dict(expected.get("final_node_outputs") or {})
    )
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
                "passed": str(expected.get("dataset_answer_contains") or "")
                in str(answer_result.get("answer") or ""),
                "actual": answer_result.get("answer"),
                "expected": expected.get("dataset_answer_contains"),
            }
        )
    if "dataset_reload_answer_contains" in expected:
        checks.append(
            {
                "name": "dataset_reload_answer_contains",
                "passed": str(expected.get("dataset_reload_answer_contains") or "")
                in str(reload_answer_result.get("answer") or ""),
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
                        task.get("body") or {"index_id": "idx-eval", "query": "5003", "top_k": 3}
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
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
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


