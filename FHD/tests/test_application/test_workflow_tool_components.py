"""Workflow dispatch precedence and the boundary between preview and writes."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pandas as pd
import pytest

from app.application.tools import workflow
from app.domain.task_lifecycle.results import execution_result_pending_state
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def dispatch_ports(monkeypatch):
    from app.application.tools.workflow_tools import dispatch
    from app.domain.app_pure import employee_pack_runner
    from app.mod_sdk import employee_tool_registry, planner_native_tools

    ports = {
        "employee_match": Mock(return_value=False),
        "employee": Mock(return_value="employee"),
        "native": Mock(return_value=(None, None)),
        "legacy": Mock(return_value=None),
        "registered": Mock(return_value={"source": "registered"}),
        "analysis": Mock(return_value={"source": "analysis"}),
    }
    monkeypatch.setattr(employee_tool_registry, "is_employee_tool", ports["employee_match"])
    monkeypatch.setattr(employee_tool_registry, "execute_employee_tool", ports["employee"])
    monkeypatch.setattr(planner_native_tools, "try_execute_native_planner_tool", ports["native"])
    monkeypatch.setattr(employee_pack_runner, "try_execute_employee_planner_tool", ports["legacy"])
    monkeypatch.setattr(dispatch, "execute_registered_workflow_tool", ports["registered"])
    monkeypatch.setattr(workflow, "handle_excel_analysis", ports["analysis"])
    return ports


def test_registered_capability_preserves_runtime_authorization_identity(
    monkeypatch, dispatch_ports
):
    authorization = object()
    runtime = {"tenant_id": "tenant-a", "_mod_authorization": authorization}
    args = {"capability": "orders.read"}
    registered = Mock(return_value="capability-result")
    monkeypatch.setattr(workflow, "execute_registered_capability", registered)

    result = workflow.execute_workflow_tool(
        workflow.ERP_CAPABILITY_TOOL_NAME, args, "/workspace/a", runtime_context=runtime
    )

    assert result == "capability-result"
    assert registered.call_args.args[0] is args
    assert registered.call_args.kwargs["runtime_context"] is runtime
    assert registered.call_args.kwargs["runtime_context"]["_mod_authorization"] is authorization
    assert registered.call_args.kwargs["workspace_root"] == "/workspace/a"
    for port in dispatch_ports.values():
        port.assert_not_called()


@pytest.mark.parametrize("owner", ["employee", "native", "legacy"])
def test_empty_extension_result_is_handled_without_fallback(owner, dispatch_ports):
    if owner == "employee":
        dispatch_ports["employee_match"].return_value = True
        dispatch_ports["employee"].return_value = ""
    elif owner == "native":
        dispatch_ports["native"].return_value = ("", "native-mod")
    else:
        dispatch_ports["legacy"].return_value = ""

    result = workflow.execute_workflow_tool("excel_analysis", {}, "/workspace/a")

    assert result == ""
    dispatch_ports["analysis"].assert_not_called()
    if owner == "employee":
        dispatch_ports["native"].assert_not_called()
    if owner in {"employee", "native"}:
        dispatch_ports["legacy"].assert_not_called()


def test_native_mod_failure_does_not_execute_legacy_or_builtin(dispatch_ports):
    failure = {
        "success": False,
        "error": "mod_execution_failed",
        "mod_id": "tenant-mod",
    }
    dispatch_ports["native"].return_value = (json.dumps(failure), "tenant-mod")

    result = workflow.execute_workflow_tool("excel_analysis", {}, db_write_token="write-token")

    assert json.loads(result) == failure
    assert dispatch_ports["native"].call_args.kwargs["db_write_token"] == "write-token"
    dispatch_ports["legacy"].assert_not_called()
    dispatch_ports["analysis"].assert_not_called()


@pytest.mark.parametrize("owner", ["employee_match", "employee", "native", "legacy"])
def test_extension_missing_receipt_cannot_fall_through_to_another_executor(owner, dispatch_ports):
    calls = []

    def fail(stage):
        def invoke(*args, **kwargs):
            calls.append(stage)
            raise RuntimeError(stage)

        return invoke

    if owner == "employee":
        dispatch_ports["employee_match"].return_value = True
    dispatch_ports[owner].side_effect = fail(owner)
    dispatch_ports["analysis"].side_effect = lambda *a, **kw: (
        calls.append("analysis") or {"ok": True}
    )

    result = json.loads(workflow.execute_workflow_tool("excel_analysis", {}))
    assert execution_result_pending_state(result) == "unknown"
    assert result["outcome"] == "unknown"
    assert result["reconciliation_required"] is True
    assert result["retryable"] is False
    assert calls == [owner]
    dispatch_ports["analysis"].assert_not_called()


def test_capability_lost_receipt_stops_before_dispatch_fallback(monkeypatch, dispatch_ports):
    execute = Mock(side_effect=ConnectionError("receipt lost after effect"))
    monkeypatch.setattr(workflow, "execute_registered_capability", execute)
    with pytest.raises(ConnectionError, match="receipt lost"):
        workflow.execute_workflow_tool(workflow.ERP_CAPABILITY_TOOL_NAME, {})
    execute.assert_called_once()
    for port in dispatch_ports.values():
        port.assert_not_called()


@pytest.mark.parametrize("legacy, scoped", [(False, True), (True, True), (True, False)])
def test_native_handler_signature_is_selected_before_one_invocation(monkeypatch, legacy, scoped):
    from types import SimpleNamespace

    from app.mod_sdk import planner_native_tools as native

    calls = []

    def old_handler(tool, args, *, workspace_root, db_write_token):
        calls.append(tool)
        return '{"success":true}'

    def new_handler(tool, args, *, workspace_root, db_write_token, runtime_context=None):
        calls.append(tool)
        raise TypeError("runtime_context failed after committing effect")

    monkeypatch.setattr(native, "is_planner_native_tools_enabled", lambda: True)
    monkeypatch.setattr(
        native,
        "_discover_native_tool_mods",
        lambda: [{"mod_id": "tenant-mod", "mod_path": "/mod", "tool_names": ["write"]}],
    )
    monkeypatch.setattr(
        native,
        "_load_handler_module",
        lambda *_: SimpleNamespace(run_native_tool=old_handler if legacy else new_handler),
    )
    raw, owner = native.try_execute_native_planner_tool(
        "write", {}, runtime_context={"turn_id": "original-turn"} if scoped else None
    )
    result = json.loads(raw)
    assert owner == "tenant-mod"
    assert result["success"] is False
    assert result["retryable"] is False
    if legacy:
        assert calls == []
        assert result["error_code"] == "tool_context_unsupported"
        assert result["execution_status"] == "not_started"
    else:
        assert calls == ["write"]
        assert result["success"] is legacy
        if not legacy:
            assert execution_result_pending_state(result) == "unknown"
            assert result["retryable"] is False


def test_template_registration_precedes_legacy_employee(monkeypatch, dispatch_ports):
    args = {"action": "create", "file_path": "quote.xlsx"}
    registered = Mock(return_value=json.dumps({"source": "registered"}))
    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability",
        registered,
    )

    assert json.loads(workflow.execute_workflow_tool("template_preview", args)) == {
        "source": "registered"
    }
    registered.assert_called_once_with(
        {"tool_id": "template_preview", "action": "create", "params": args},
        workspace_root=None,
        runtime_context=None,
    )
    dispatch_ports["registered"].assert_not_called()
    dispatch_ports["legacy"].assert_not_called()


@pytest.fixture
def owned_csv_capability(tmp_path, monkeypatch, trusted_actor):
    import io
    from types import SimpleNamespace

    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.elt.service_uploads import register_chat_upload

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    actor = trusted_actor(user_id=17, role="admin")
    upload = register_chat_upload(
        user=SimpleNamespace(id=actor.user_id, tenant_id=actor.tenant_id),
        filename="source.csv",
        content_type="text/csv",
        stream=io.BytesIO(b"item,count\npaint,2\nprimer,1\nbrush,5\nseal,0\n"),
    )
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    repo._ensure_schema()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    return SimpleNamespace(actor=actor, upload=upload, repo=repo)


@pytest.mark.parametrize("action", ["read", "structure", "query", "statistics"])
def test_excel_read_actions_use_registered_contract_and_real_owned_upload(
    action, owned_csv_capability
):
    from app.application.agent_orchestrator.result_verification import summarize_verification
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    actor = owned_csv_capability.actor
    repo = owned_csv_capability.repo
    params = {"file_path": owned_csv_capability.upload["upload_id"]}
    if action == "read":
        params["max_rows"] = 1
    if action == "query":
        params["query_expression"] = "count > 1 and item in ['paint', 'brush']"
    context = {**actor.context, "idempotency_key": f"canonical-owned-{action}"}
    args = {
        "tool_id": "excel_analysis",
        "action": action,
        "params": params,
    }
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME, args, runtime_context=context
        )
    )
    assert result["success"] is True, json.dumps(result)
    run = repo.get(result["run_id"])
    assert run.status == "completed"
    assert run.user_id == str(actor.user_id)
    assert len(run.tool_calls) == 1
    assert run.steps[0].tool_id == "excel_analysis"
    assert run.steps[0].action == action
    assert get_tool_action_spec("excel_analysis", action).read_only is True
    assert get_tool_action_spec("excel_analysis", "export").read_only is False
    verification = summarize_verification(run)
    assert verification["accepted"] is True
    assert verification["steps"][0]["status"] == "not_required"
    assert verification["independently_verified_steps"] == 0
    assert verification["contract_only_steps"] == 1
    output = run.steps[0].output
    data = output["data"]
    if action == "read":
        assert data["records"] == [{"item": "paint", "count": 2}]
        assert output["returned_rows"] == 1
        assert output["has_more"] is True
    elif action == "structure":
        assert data["dtypes"]["item"] in {"object", "str", "string"}
        assert data["dtypes"]["count"] == "int64"
        assert {key: value for key, value in data.items() if key != "dtypes"} == {
            "row_count": 4,
            "column_count": 2,
            "columns": ["item", "count"],
            "sample_rows": [
                {"item": "paint", "count": 2},
                {"item": "primer", "count": 1},
                {"item": "brush", "count": 5},
            ],
        }
        assert "llm_understanding" not in output
    elif action == "query":
        assert data["records"] == [{"item": "paint", "count": 2}, {"item": "brush", "count": 5}]
        assert data["row_count"] == 2
    else:
        assert output["row_count"] == 4
        assert output["numeric_summary"]["count"] == {
            "count": 4,
            "sum": 8,
            "mean": 2,
            "min": 0,
            "max": 5,
        }
    replay = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME, args, runtime_context=context
        )
    )
    assert replay["run_id"] == result["run_id"]
    assert replay["deduplicated"] is True
    assert len(repo.get(result["run_id"]).tool_calls) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "df.to_csv({target})",
        "pd.read_csv('https://example.invalid/source.csv')",
        "__import__('pathlib').Path({target}).write_text('changed')",
    ],
)
def test_excel_query_rejects_call_expressions_without_file_or_network_effects(
    expression, owned_csv_capability, tmp_path, monkeypatch
):
    from pathlib import Path

    target = tmp_path / "must-not-be-written.csv"
    effects = tmp_path / "forbidden-query-effect.txt"
    expression = expression.format(target=repr(str(target)))
    read_csv = pd.read_csv

    def owned_input_only(path, *args, **kwargs):
        assert isinstance(path, Path)
        assert path.name == "input.csv"
        return read_csv(path, *args, **kwargs)

    def forbidden_effect(*args, **kwargs):
        # Tool execution can fork; record attempted I/O where the parent can observe it.
        effects.write_text("unexpected query I/O", encoding="utf-8")
        raise AssertionError("query cannot write files or access the network")

    monkeypatch.setattr(pd, "read_csv", owned_input_only)
    monkeypatch.setattr(pd.DataFrame, "to_csv", forbidden_effect)
    monkeypatch.setattr("urllib.request.urlopen", forbidden_effect)
    context = {**owned_csv_capability.actor.context, "idempotency_key": "reject-expression-call"}
    args = {
        "tool_id": "excel_analysis",
        "action": "query",
        "params": {
            "file_path": owned_csv_capability.upload["upload_id"],
            "query_expression": expression,
        },
    }
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME, args, runtime_context=context
        )
    )
    assert result["success"] is False
    run = owned_csv_capability.repo.get(result["run_id"])
    assert run.steps[0].output["error_code"] == "invalid_query_expression"
    assert len(run.tool_calls) == 1
    assert not target.exists()
    assert not effects.exists()


@pytest.mark.parametrize("expression", [None, "", "   "])
def test_excel_query_requires_nonempty_expression_before_admission(
    expression, owned_csv_capability
):
    params = {
        "file_path": owned_csv_capability.upload["upload_id"],
    }
    if expression is not None:
        params["query_expression"] = expression
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME,
            {"tool_id": "excel_analysis", "action": "query", "params": params},
            runtime_context={
                **owned_csv_capability.actor.context,
                "idempotency_key": "missing-query-expression",
            },
        )
    )
    assert result["success"] is False
    assert result["error_code"] == "schema_validation_failed"
    assert result["execution_status"] == "not_started"
    assert not result.get("run_id")


def test_office_generation_stays_in_original_approval_chain(tmp_path, monkeypatch, trusted_actor):
    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.tools.workflow_tools import adapters

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    actor = trusted_actor(user_id=17, role="admin")
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    repo._ensure_schema()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    generate = Mock(side_effect=AssertionError("approval must precede document generation"))
    store = Mock(side_effect=AssertionError("approval must precede artifact storage"))
    monkeypatch.setattr(adapters, "generate_document", generate)
    monkeypatch.setattr(adapters, "store_document", store)
    context = {**actor.context, "idempotency_key": "canonical-office-original"}
    args = {
        "tool_id": "generate_office_document",
        "action": "execute",
        "params": {"user_request": "Generate a quote", "output_format": "docx"},
    }
    first = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME, args, runtime_context=context
        )
    )
    assert first["success"] is False
    assert first["execution_state"] == "waiting_approval", json.dumps(first)
    assert first["pending_approval"] is True
    assert first["approval_request_id"]
    run = repo.get(first["run_id"])
    assert run.status == "waiting_user"
    assert run.steps[0].tool_id == "generate_office_document"
    assert run.tool_calls == []
    repeated = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME, args, runtime_context=context
        )
    )
    assert repeated["run_id"] == first["run_id"]
    assert repeated["deduplicated"] is True
    generate.assert_not_called()
    store.assert_not_called()


@pytest.mark.parametrize("query_kind", ["question", "query_expression"])
def test_registered_excel_query_uses_one_read_only_path(
    query_kind, owned_csv_capability, monkeypatch, local_tools
):
    from types import SimpleNamespace

    model = Mock(return_value=SimpleNamespace(data={"query_expression": "c1 > 1"}))
    monkeypatch.setattr(
        "app.infrastructure.excel.pandas_translator.complete_structured_sync", model
    )
    case = owned_csv_capability
    params = {
        "file_path": case.upload["upload_id"],
        query_kind: (
            "Which items have more than one unit?" if query_kind == "question" else "count > 1"
        ),
    }
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME,
            {"tool_id": "excel_analysis", "action": "query", "params": params},
            runtime_context={**case.actor.context, "idempotency_key": "query-" + query_kind},
        )
    )
    assert result["success"] is True, result
    run = case.repo.get(result["run_id"])
    assert run.metadata["verification"]["accepted"] is True
    assert run.steps[0].output["data"]["records"] == [
        {"item": "paint", "count": 2},
        {"item": "brush", "count": 5},
    ]
    assert model.call_count == (1 if query_kind == "question" else 0)
    assert len(run.tool_calls) == 1


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"question": ""},
        {"query_expression": " "},
        {"question": "more than one", "query_expression": "count > 1"},
    ],
)
def test_registered_excel_query_rejects_missing_or_ambiguous_input(
    query, owned_csv_capability, monkeypatch
):
    model = Mock(side_effect=AssertionError("invalid request cannot call a model"))
    monkeypatch.setattr(
        "app.infrastructure.excel.pandas_translator.complete_structured_sync", model
    )
    case = owned_csv_capability
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME,
            {
                "tool_id": "excel_analysis",
                "action": "query",
                "params": {"file_path": case.upload["upload_id"], **query},
            },
            runtime_context=case.actor.context,
        )
    )
    assert result["success"] is False, result
    assert result["execution_status"] == "not_started"
    assert case.repo.list_recent(user_id=str(case.actor.user_id)) == []
    model.assert_not_called()


@pytest.mark.parametrize(
    "plan",
    [
        {"code": "result = df"},
        {"query_expression": "__import__('os').getenv('TOKEN')"},
        {"query_expression": "pd.read_csv('https://example.invalid/private')"},
    ],
)
def test_registered_natural_query_rejects_generated_code(
    plan, owned_csv_capability, monkeypatch, local_tools
):
    from types import SimpleNamespace

    model = Mock(return_value=SimpleNamespace(data=plan))
    monkeypatch.setattr(
        "app.infrastructure.excel.pandas_translator.complete_structured_sync", model
    )
    case = owned_csv_capability
    result = json.loads(
        workflow.execute_workflow_tool(
            workflow.ERP_CAPABILITY_TOOL_NAME,
            {
                "tool_id": "excel_analysis",
                "action": "query",
                "params": {
                    "file_path": case.upload["upload_id"],
                    "question": "Summarize the uploaded rows",
                },
            },
            runtime_context=case.actor.context,
        )
    )
    assert result["success"] is False, result
    run = case.repo.get(result["run_id"])
    assert len(run.tool_calls) == 1 and run.steps[0].output["success"] is False
    assert run.steps[0].output["error"] in {"query_translation_failed", "invalid_pandas_query"}
    assert model.call_count in {1, 2}
