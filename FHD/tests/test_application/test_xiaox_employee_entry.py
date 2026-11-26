"""Employee entry preserves host identity and the exact pre-existing tool scope.

The gateway is replaced at the runtime boundary; these are entry/permission
regressions, not real-model or real-Xiaox acceptance tests.
"""

from __future__ import annotations

import inspect
import time
from copy import deepcopy
from unittest.mock import MagicMock, Mock

import pytest

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.agent_runtime import gateway
from app.application.employee_runtime import agent_runner, executor
from app.application.tools.workflow_tools.catalog_excel import excel_tool_specs
from app.infrastructure.xiaox import policy
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _read_contract():
    # A stored employee declaration is checked against the one current schema.
    return {
        "type": "function",
        "function": {
            "name": "business_db_read",
            "parameters": deepcopy(get_tool_action_spec("business_db", "read").input_schema),
        },
    }


def _allow(name, arguments):
    return {"ok": True}


@pytest.fixture
def runtime_boundary(monkeypatch):
    captured = []

    def runtime(**kwargs):
        inspect.signature(gateway.run_runtime_task_async).bind(**kwargs)
        captured.append(kwargs)
        return {
            "handler": "agent",
            "runtime": "xiaox",
            "ok": True,
            "output": "synthetic verified receipt",
            "business_completed": True,
            "exit_status": "completed",
            "tool_calls": [],
            "trajectory": [],
        }

    def forbid_legacy(*args, **kwargs):
        raise AssertionError("Selected Xiaox must not contact the native model")

    monkeypatch.setattr(gateway, "run_runtime_task", runtime)
    monkeypatch.setattr("app.infrastructure.llm.client.require_api_key", forbid_legacy)
    monkeypatch.setattr(agent_runner, "_chat_completion", forbid_legacy)
    return captured


def _run(**kwargs):
    return agent_runner.run_employee_agent_loop(
        employee_id="clerk",
        system_prompt="employee instructions",
        task="read data",
        **kwargs,
    )


def _excel_read_tool():
    tool = deepcopy(excel_tool_specs()[0])
    tool["function"]["parameters"]["properties"]["action"]["enum"] = ["read"]
    return tool


def test_read_alias_cannot_grant_write_or_change_original_entity_scope(runtime_boundary):
    calls = []

    def gate(name, arguments):
        calls.append((name, arguments))
        return {"ok": True}

    result = _run(tools=[business_db_tool_specs()[0]], gate=gate)
    assert result["runtime"] == "xiaox"
    submitted = runtime_boundary[0]
    assert submitted["allowed_actions"] == ["business_db.read"]
    check = submitted["gate"]
    assert check("business_db", "read", {"entity": "customers"})["ok"] is True
    assert calls == [("business_db_read", {"entity": "customers"})]
    assert check("business_db", "write", {"entity": "customers"})["ok"] is False
    assert check("business_db", "read", {"entity": "users"})["ok"] is False
    assert check("business_db", "read", {"entity": "customers", "action": "write"})["ok"] is False
    assert len(calls) == 1


def test_action_enum_and_original_gate_survive_the_runtime_boundary(runtime_boundary):
    calls = []

    def gate(name, arguments):
        calls.append((name, arguments))
        return {"ok": False, "pending_approval": True, "reason": "approval required"}

    _run(tools=[_excel_read_tool()], gate=gate)
    submitted = runtime_boundary[0]
    assert submitted["allowed_actions"] == ["excel_analysis.read"]
    check = submitted["gate"]
    params = {"file_path": "in/report.xlsx"}
    verdict = check("excel_analysis", "read", params)
    assert verdict["pending_approval"] is True
    assert calls == [("excel_analysis", {**params, "action": "read"})]
    assert "action" not in params
    assert check("excel_analysis", "export", params)["ok"] is False
    assert check("excel_analysis", "read", {**params, "action": "export"})["ok"] is False
    assert check("excel_analysis", "read", {})["ok"] is False
    assert len(calls) == 1


@pytest.mark.parametrize(
    "entity_schema",
    [
        {"const": "customers"},
        {"$ref": "https://unauthorized.example/contract.json"},
    ],
)
def test_parameter_schema_restrictions_never_expand_or_fetch_remote_references(
    runtime_boundary,
    entity_schema,
):
    tool = deepcopy(_read_contract())
    tool["function"]["parameters"]["properties"]["entity"] = entity_schema
    _run(tools=[tool], gate=_allow)
    check = runtime_boundary[0]["gate"]
    assert check("business_db", "read", {"entity": "products"})["ok"] is False
    assert check("business_db", "read", {"entity": "customers"})["ok"] is ("const" in entity_schema)


@pytest.mark.parametrize(
    "tool",
    [
        {"function": {"name": "business_db", "parameters": {"type": "object"}}},
        {"function": {"name": "excel_chart_recommend", "parameters": {"type": "object"}}},
        {"function": {"name": "products_bulk_import", "parameters": {"type": "object"}}},
        {
            "function": {
                "name": "excel_analysis",
                "parameters": {
                    "type": "object",
                    "properties": {"action": {"type": "string"}},
                },
            }
        },
    ],
)
def test_ambiguous_or_unregistered_tool_is_unsupported_without_fallback(runtime_boundary, tool):
    result = _run(tools=[tool], gate=_allow)
    assert result["error_code"] == "employee_runtime_tools_unsupported"
    assert result["ok"] is False
    assert result["legacy_fallback_allowed"] is False
    assert runtime_boundary == []


def test_missing_original_gate_is_not_hidden_by_schema_adapter(runtime_boundary):
    result = _run(tools=[_read_contract()])
    assert result["error_code"] == "gate_required"
    assert runtime_boundary == []


def test_empty_allowlist_stays_empty_and_untrusted_payload_cannot_supply_identity(runtime_boundary):
    _run(
        tools=[],
        gate=_allow,
        input_data={
            "user_id": "forged",
            "tenant_id": "forged",
            "turn_id": "forged",
            "runtime_context": {"_actor_authorization": "forged"},
        },
    )
    submitted = runtime_boundary[0]
    assert submitted["allowed_actions"] == []
    assert submitted["runtime_context"] == {"employee_id": "clerk", "source": "employee_runtime"}
    assert submitted["gate"]("business_db", "read", {"entity": "customers"})["ok"] is False


def test_retry_correlation_uses_trusted_parent_and_node_not_random_id(runtime_boundary):
    context = {"parent_run_id": "parent-1", "step_id": "step-2", "user_id": "41"}
    for _ in range(2):
        _run(tools=[], gate=_allow, runtime_context=context)
    _run(tools=[], gate=_allow, runtime_context={**context, "step_id": "step-3"})
    ids = [call["runtime_context"]["turn_id"] for call in runtime_boundary]
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]
    assert "turn_id" not in context


def test_workflow_nodes_are_scoped_under_the_actual_durable_parent(runtime_boundary):
    context = {"run_id": "current-run", "parent_run_id": "grandparent", "turn_id": "chat-turn"}
    _run(tools=[], gate=_allow, runtime_context={**context, "step_id": "node-a"})
    _run(tools=[], gate=_allow, runtime_context={**context, "step_id": "node-b"})
    first, second = [row["runtime_context"] for row in runtime_boundary]
    assert first["parent_run_id"] == second["parent_run_id"] == "current-run"
    assert first["turn_id"] != second["turn_id"]
    assert first["turn_id"] != "chat-turn"


def test_xiaox_preserves_the_inherited_employee_deadline(runtime_boundary, monkeypatch):
    from app.application.tool_execution_deadline import (
        invocation_deadline,
        remaining_invocation_seconds,
    )

    observed = []

    def runtime(**kwargs):
        observed.append(remaining_invocation_seconds(9999))
        return {"ok": False}

    monkeypatch.setattr(gateway, "run_runtime_task", runtime)
    with invocation_deadline(time.monotonic() + 0.5):
        _run(tools=[], gate=_allow, wall_time_limit_sec=300)
    assert 0 < observed[0] <= 0.5


@pytest.mark.parametrize(
    "settings",
    [
        policy.RuntimeSettings(engine="native"),
        policy.RuntimeSettings(engine="xiaox", surfaces=("chat",)),
    ],
)
def test_retired_engine_and_unselected_surface_fail_without_native_fallback(
    runtime_boundary, settings
):
    result = _run(tools=[], settings=settings)
    assert result["error_code"] == "runtime_configuration_invalid"
    assert result["legacy_fallback_allowed"] is False
    assert runtime_boundary == []


def test_default_configuration_is_deferred_to_authenticated_gateway(monkeypatch, runtime_boundary):
    def invalid():
        raise policy.RuntimePolicyError("bad deployment")

    monkeypatch.setattr(policy, "runtime_settings", invalid)
    assert _run(tools=[], gate=_allow)["ok"] is True
    assert runtime_boundary[0]["settings"] is None


@pytest.fixture
def employee(monkeypatch, tmp_path):
    from app.application.employee_runtime import agent, metrics, task_continuity
    from app.application.employee_runtime.memory import MemoryContext

    config = {
        "actions": {"handlers": ["agent"]},
        "cognition": {"agent": {"system_prompt": "clerk role"}},
        "workspace_policy": {"forbidden_globs": ["secret/**"]},
    }
    pack = {"pack_id": "clerk", "version": "1", "pack_dir": str(tmp_path), "manifest": {}}
    manager = MagicMock()
    manager.recall.return_value = MemoryContext(long_term_prompt="trusted memory context")
    monkeypatch.setattr(agent, "load_employee_pack_from_disk", lambda _: pack)
    monkeypatch.setattr(agent, "parse_employee_config_v2", lambda _: config)
    monkeypatch.setattr(agent, "gate_action_or_block", lambda *args: {"ok": True})
    monkeypatch.setattr(agent, "EmployeeMemoryManager", lambda *args, **kwargs: manager)
    monkeypatch.setattr(agent, "build_employee_context", lambda *args: None)
    monkeypatch.setattr(
        task_continuity, "maybe_continue_employee_task", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(metrics, "record_employee_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.mod_sdk.product_plane.employee_execution_block_reason", lambda *args: ""
    )
    employee = agent.EmployeeAgent("clerk")
    monkeypatch.setattr(employee, "_run_upstream_collaboration", lambda *args, **kwargs: None)
    monkeypatch.setattr(employee, "_augment_config_with_persona", lambda config, _: config)
    monkeypatch.setattr(
        employee, "_perceive", lambda config, payload: {"normalized_input": payload}
    )
    monkeypatch.setattr(
        agent.EmployeeAgent, "_build_agent_tools", lambda *args: [_excel_read_tool()]
    )
    return employee, config


def test_real_employee_call_chain_preserves_trusted_context_and_workspace_gate(
    employee, runtime_boundary, tmp_path
):
    actor, _ = employee
    trusted = {
        "user_id": "41",
        "tenant_id": "1",
        "_actor_authorization": "server sealed identity",
        "turn_id": "persisted-turn-7",
        "session_id": "session-1",
    }
    payload = {
        "user_id": "attacker",
        "tenant_id": "attacker",
        "workspace_root": "/outside",
        "runtime_context": {"user_id": "attacker", "human_approved": True},
        "human_approved": True,
        "approved_by": "attacker",
        "call_id": "foreign-call",
    }
    events = []
    result = actor.run(
        "read report",
        payload,
        user_id=41,
        runtime_context=trusted,
        workspace_root=str(tmp_path),
        on_event=events.append,
    )
    assert result["success"] is True
    submitted = runtime_boundary[0]
    assert submitted["runtime_context"]["user_id"] == "41"
    assert submitted["runtime_context"]["_actor_authorization"] == "server sealed identity"
    assert submitted["runtime_context"]["turn_id"] == "persisted-turn-7"
    assert submitted["runtime_context"]["workspace_root"] == str(tmp_path)
    assert all(
        key not in submitted["runtime_context"]
        for key in ("human_approved", "approved_by", "call_id")
    )
    assert submitted["completion_mode"] == "auto"
    assert "admit_goal" not in submitted
    assert "clerk role" in submitted["system_prompt"]
    assert "trusted memory context" in submitted["system_prompt"]
    submitted["on_event"]({"method": "turn/started"})
    assert events == [{"method": "turn/started"}]
    check = submitted["gate"]
    assert check("excel_analysis", "read", {"file_path": "public/report.xlsx"})["ok"] is True
    assert check("excel_analysis", "read", {"file_path": "secret/passwords.xlsx"})["ok"] is False
    assert "employee_id" not in trusted
    assert payload["workspace_root"] == "/outside"


def test_mixed_handlers_are_rejected_before_native_cognition(employee, runtime_boundary):
    actor, config = employee
    config["actions"]["handlers"] = ["agent", "direct_python"]
    result = actor.run("execute")
    assert result["success"] is False
    assert result["error_code"] == "employee_runtime_handlers_unsupported"
    assert runtime_boundary == []


def test_http_resume_can_restore_the_original_employee_gate(employee, runtime_boundary, tmp_path):
    from app.application.employee_runtime.agent import restore_xiaox_employee_gate

    actor, _ = employee
    actor.run("read", workspace_root=str(tmp_path), runtime_context={"turn_id": "turn-1"})
    original = runtime_boundary[0]
    actions, check = restore_xiaox_employee_gate(
        "clerk",
        original["runtime_context"],
        input_data=original["input_data"],
    )
    assert actions == original["allowed_actions"]
    assert check("excel_analysis", "read", {"file_path": "secret/passwords.xlsx"})["ok"] is False
    assert check("excel_analysis", "read", {"file_path": "public/report.xlsx"})["ok"] is True


@pytest.mark.parametrize("changed", ["config", "binding", "tools"])
def test_resume_rejects_missing_or_changed_employee_authority(
    employee,
    runtime_boundary,
    monkeypatch,
    changed,
):
    from app.application.employee_runtime.agent import EmployeeAgent, restore_xiaox_employee_gate

    actor, config = employee
    actor.run("read", runtime_context={"turn_id": "turn-1"})
    original = runtime_boundary[0]
    if changed == "config":
        config["workspace_policy"]["forbidden_globs"] = []
    elif changed == "binding":
        original["runtime_context"].pop("_employee_gate_contract")
    else:
        tool = _excel_read_tool()
        tool["function"]["parameters"]["properties"]["action"]["enum"].append("export")
        monkeypatch.setattr(EmployeeAgent, "_build_agent_tools", lambda *args: [tool])
    with pytest.raises(ValueError):
        restore_xiaox_employee_gate(
            "clerk",
            original["runtime_context"],
            input_data=original["input_data"],
        )


def test_handler_delegation_keeps_trusted_history_and_context_outside_input(
    runtime_boundary, tmp_path
):
    context = {"user_id": "41", "client_request_id": "request-9"}
    history = [{"role": "user", "content": "earlier request"}]
    executor._actions_fhd(
        {"actions": {"handlers": ["agent"]}},
        {"history": history, "input": {"user_id": "forged"}},
        "read",
        "clerk",
        tmp_path,
        None,
        agent_tools=[_read_contract()],
        agent_gate=_allow,
        runtime_context=context,
    )
    submitted = runtime_boundary[0]
    assert submitted["runtime_context"]["user_id"] == "41"
    assert submitted["runtime_context"]["turn_id"] == "request-9"
    assert submitted["history"] == history
    assert submitted["input_data"] == {"user_id": "forged"}


def test_employee_keeps_sole_runtime_when_account_configuration_is_unavailable(
    employee, runtime_boundary, monkeypatch
):
    actor, _ = employee
    monkeypatch.setattr(
        gateway,
        "run_runtime_task",
        lambda **_: agent_runner._runtime_entry_error(
            "runtime_configuration_required", "请核对当前账号的模型设置"
        ),
    )
    result = actor.run("read")
    assert result["success"] is False
    assert "模型设置" in str(result)
    assert runtime_boundary == []


@pytest.mark.parametrize(
    "manifest, config, expected",
    [
        (
            {},
            {},
            {
                "excel_analysis.read",
                "excel_analysis.structure",
                "excel_analysis.aggregate",
                "generate_office_document.execute",
            },
        ),
        (
            {"employee": {"capabilities": ["Excel 数据分析"]}},
            {},
            {"excel_join_compare.join", "excel_join_compare.diff"},
        ),
        (
            {"employee": {"capabilities": ["批量导入"]}},
            {},
            {"elt_import.preview", "elt_import.execute"},
        ),
        (
            {},
            {"tools": ["business_db.read", "business_db.write"]},
            {"business_db.read", "business_db.write"},
        ),
    ],
)
def test_default_and_erp_employee_scopes_have_real_canonical_actions(
    monkeypatch, manifest, config, expected, trusted_actor
):
    from app.application.employee_runtime.tool_scope import resolve_employee_tools

    monkeypatch.setattr("app.application.agent_tool_lifecycle.discovery_for_runtime", lambda _: [])
    declared = resolve_employee_tools("clerk", manifest, config)
    actions, _ = agent_runner._xiaox_employee_tool_scope(declared, _allow)
    assert expected.issubset(actions)
    assert all("products_bulk_import" not in action for action in actions)


@pytest.mark.parametrize(
    "change", ["none", "path", "pack", "actions", "contract", "cancelled", "unknown"]
)
def test_durable_child_rebuilds_employee_scope_before_effect(
    employee, runtime_boundary, trusted_actor, monkeypatch, tmp_path, change
):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    principal = trusted_actor(permissions=["tool.excel_analysis.read"])
    actor, config = employee
    actor.run(
        "read",
        user_id=principal.user_id,
        workspace_root=str(tmp_path),
        runtime_context={**principal.context, "turn_id": "original-turn"},
    )
    original = runtime_boundary[0]
    parent = AgentRun(user_id=str(principal.user_id), message="read", status="waiting_user")
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_gate_required=True,
        runtime_context=deepcopy(original["runtime_context"]),
        runtime_allowed_actions=original["allowed_actions"],
        _xiaox_input_data=original["input_data"],
    )
    if change == "actions":
        parent.metadata["runtime_allowed_actions"] = [
            "excel_analysis.read",
            "excel_analysis.export",
        ]
    if change in {"cancelled", "unknown"}:
        parent.status = change
    SQLAlchemyAgentRunRepository(session_factory=principal.factory).save(parent)
    reopened = SQLAlchemyAgentRunRepository(session_factory=principal.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: reopened,
    )
    context = {
        **original["runtime_context"],
        "parent_run_id": parent.run_id,
        "run_id": "child",
        "source": "xiaox_runtime",
    }
    if change == "pack":
        config["workspace_policy"]["forbidden_globs"] = []
    if change == "contract":
        context.pop("_employee_gate_contract")
    dispatch = Mock(return_value={"success": True, "data": {"records": []}})
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    step = AgentStep(
        node_id="read",
        tool_id="excel_analysis",
        action="read",
        params={
            "file_path": "secret/passwords.xlsx" if change == "path" else "public/report.xlsx",
        },
    )
    result = AgentToolExecutor().execute(step, runtime_context=context)
    if change == "none":
        assert result["success"] is True
        dispatch.assert_called_once()
    else:
        assert result["error_code"] == "employee_gate_denied"
        dispatch.assert_not_called()


def test_employee_document_write_uses_one_durable_child_approval(
    employee, runtime_boundary, trusted_actor, monkeypatch, tmp_path
):
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    principal = trusted_actor(permissions=["tool.generate_office_document.execute"])
    actor, _ = employee
    document = {
        "type": "function",
        "function": {
            "name": "generate_office_document",
            "parameters": deepcopy(
                get_tool_action_spec("generate_office_document", "execute").input_schema
            ),
        },
    }
    monkeypatch.setattr(actor, "_build_agent_tools", lambda *args: [document])
    old_gate = Mock(side_effect=AssertionError("No parallel approval owner may be created"))
    monkeypatch.setattr(
        "app.application.employee_runtime.write_approval.build_write_approval_gate", old_gate
    )
    actor.run(
        "生成合同",
        user_id=principal.user_id,
        workspace_root=str(tmp_path),
        runtime_context={**principal.context, "turn_id": "document-turn"},
    )
    original = runtime_boundary[0]
    params = {"user_request": "生成合同", "output_format": "docx"}
    parent = AgentRun(user_id=str(principal.user_id), message="生成合同", status="running")
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_gate_required=True,
        runtime_context=original["runtime_context"],
        runtime_allowed_actions=original["allowed_actions"],
    )
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository = SQLAlchemyAgentRunRepository(session_factory=principal.factory)
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(
        parent.run_id,
        allowed_actions=original["allowed_actions"],
        runtime_config={"gate_required": True},
    )
    bridge = XiaoxToolBridge(store, AgentOrchestrator(repository=repository), gate=original["gate"])
    args = {
        "call_id": "document",
        "tool_id": "generate_office_document",
        "action": "execute",
        "params": params,
        "schema_digest": bridge.invoke(
            grant.mcp_token,
            "capability_describe",
            {
                "tool_id": "generate_office_document",
                "action": "execute",
            },
        )["capability"]["schema_digest"],
    }
    first = bridge.invoke(grant.mcp_token, "execute_action", args)
    second = bridge.invoke(grant.mcp_token, "execute_action", {**args, "call_id": "model-retry"})
    assert first["status"] == "waiting_user" and first["pending_approval"] is True
    assert first["run_id"] == second["run_id"] != parent.run_id
    assert first["approval_card"]["run_id"] == first["run_id"]
    assert len(repository.list_recent()) == 2
    assert first["tool_calls"] == []
    old_gate.assert_not_called()
    for tool_id, action in (
        ("generate_office_document", "execute"),
        ("elt_import", "execute"),
        ("business_db", "write"),
    ):
        spec = get_tool_action_spec(tool_id, action)
        assert spec is not None and not (spec.read_only and spec.risk == "low")
