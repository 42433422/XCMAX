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
            first_chunk_id = str(
                (reference.hits[0] if reference.hits else {}).get("chunk_id") or ""
            )
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
    from app.domain.shared_services.user_memory_service import UserMemoryService, reset_user_memory_service

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
    _check_equal(
        checks, "deleted_status", dict(deleted.get("memory") or {}).get("status"), "deleted"
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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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
        patch(
            "app.domain.shared_services.user_memory_service.get_user_memory_service", return_value=memory_service
        ),
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
    from app.domain.shared_services.user_memory_service import UserMemoryService, reset_user_memory_service

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
    _check_equal(
        checks, "trusted.source_policy", trusted_candidate.get("source_policy"), "trusted_pending"
    )
    _check_equal(
        checks,
        "trusted.confirmed_status",
        dict(confirmed.get("memory") or {}).get("status"),
        "active",
    )
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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

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


def _check_tool_calls(
    checks: list[dict[str, Any]], tool_calls: list[Any], expected: list[dict[str, Any]]
) -> None:
    for index, expected_call in enumerate(expected):
        actual_call = tool_calls[index] if index < len(tool_calls) else None
        for key, expected_value in expected_call.items():
            actual_value = getattr(actual_call, key, None) if actual_call is not None else None
            _check_equal(checks, f"tool_calls[{index}].{key}", actual_value, expected_value)


def _check_step_attempts(
    checks: list[dict[str, Any]], steps: list[Any], expected: list[int]
) -> None:
    for index, expected_count in enumerate(expected):
        actual_step = steps[index] if index < len(steps) else None
        actual_value = (
            getattr(actual_step, "attempt_count", None) if actual_step is not None else None
        )
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
        actual_params = (
            dict(getattr(actual_step, "params", {}) or {}) if actual_step is not None else {}
        )
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


def _check_event_types(
    checks: list[dict[str, Any]], events: list[Any], expected: list[str]
) -> None:
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


def _check_step_errors(
    checks: list[dict[str, Any]], steps: list[Any], expected_fragments: list[str]
) -> None:
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


def _result(
    task: dict[str, Any], checks: list[dict[str, Any]], details: dict[str, Any]
) -> dict[str, Any]:
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
    parser = argparse.ArgumentParser(description="Run offline agent contract fixtures.")
    parser.add_argument(
        "--tasks",
        type=Path,
        default=DEFAULT_TASKS_PATH,
        help="Path to JSONL eval tasks.",
    )
    args = parser.parse_args(argv)
    result = run_eval(args.tasks)
    public_summary = {
        "suite": "agent_platform_minimum",
        "tasks_path": str(args.tasks),
        "execution_mode": "fixture_local",
        **{key: result[key] for key in ("total", "passed", "failed", "score")},
    }
    print(json.dumps(public_summary, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
