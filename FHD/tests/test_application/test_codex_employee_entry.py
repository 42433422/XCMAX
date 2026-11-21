"""Employee entry preserves host identity and the exact pre-existing tool scope.

The gateway is replaced at the runtime boundary; these are entry/permission
regressions, not real-model or real-Codex acceptance tests.
"""

from __future__ import annotations

import inspect
import time
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from app.application.agent_runtime import gateway
from app.application.employee_runtime import agent_loop, agent_runner, executor
from app.infrastructure.codex import policy


def business_db_tool_specs():
    # Historical alias declarations remain contract fixtures, not executable
    # legacy modules. Product calls still resolve against the current ToolSpec.
    return [
        {
            "function": {
                "name": "business_db_read",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "enum": ["customers", "products", "materials", "shipment_records"],
                        }
                    },
                    "required": ["entity"],
                },
            }
        }
    ]


def excel_tool_specs():
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    spec = get_tool_action_spec("excel_analysis", "read")
    assert spec is not None
    schema = deepcopy(spec.input_schema)
    schema.setdefault("properties", {})["action"] = {
        "type": "string",
        "enum": ["read", "aggregate"],
    }
    schema.setdefault("required", []).append("action")
    return [
        {"function": {"name": "excel_analysis", "parameters": schema}},
        {"function": {"name": "schema_understand", "parameters": {"type": "object"}}},
    ]


def _allow(name, arguments):
    return {"ok": True}


@pytest.fixture
def runtime_boundary(monkeypatch):
    captured = []
    settings = policy.RuntimeSettings(engine="codex")

    def runtime(**kwargs):
        inspect.signature(gateway.run_runtime_task_async).bind(**kwargs)
        captured.append(kwargs)
        return {
            "handler": "agent",
            "runtime": "codex",
            "ok": True,
            "output": "synthetic verified receipt",
            "business_completed": True,
            "exit_status": "completed",
            "tool_calls": [],
            "trajectory": [],
        }

    def forbid_legacy(*args, **kwargs):
        raise AssertionError("Selected Codex must not contact the native model")

    monkeypatch.setattr(policy, "runtime_settings", lambda: settings)
    monkeypatch.setattr(gateway, "run_runtime_task", runtime)
    monkeypatch.setattr("app.infrastructure.llm.client.require_api_key", forbid_legacy)
    monkeypatch.setattr(agent_runner, "_chat_completion", forbid_legacy)
    return captured


def _run(**kwargs):
    return agent_loop.run_employee_agent_loop(
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
    assert result["runtime"] == "codex"
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
    tool = deepcopy(business_db_tool_specs()[0])
    tool["function"]["parameters"]["properties"]["entity"] = entity_schema
    _run(tools=[tool], gate=_allow)
    check = runtime_boundary[0]["gate"]
    assert check("business_db", "read", {"entity": "products"})["ok"] is False
    assert check("business_db", "read", {"entity": "customers"})["ok"] is ("const" in entity_schema)


@pytest.mark.parametrize(
    "tool",
    [
        {"function": {"name": "business_db", "parameters": {"type": "object"}}},
        excel_tool_specs()[0],  # aggregate has no registered canonical action.
        excel_tool_specs()[1],  # schema_understand has no equivalent canonical function.
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
    result = _run(tools=[business_db_tool_specs()[0]])
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


def test_codex_preserves_the_inherited_employee_deadline(runtime_boundary, monkeypatch):
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
        policy.RuntimeSettings(),
        policy.RuntimeSettings(engine="codex", surfaces=("chat",)),
    ],
)
def test_native_default_and_unselected_surface_keep_existing_path(
    monkeypatch, runtime_boundary, settings
):
    def no_key():
        raise RuntimeError("not configured")

    monkeypatch.setattr(policy, "runtime_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.llm.client.require_api_key", no_key)
    result = _run(tools=[])
    assert result["error_code"] == "employee_llm_not_configured"
    assert runtime_boundary == []


def test_invalid_deployment_config_never_falls_through_to_native(monkeypatch, runtime_boundary):
    def invalid():
        raise policy.RuntimePolicyError("bad deployment")

    monkeypatch.setattr(policy, "runtime_settings", invalid)
    assert _run(tools=[], gate=_allow)["error_code"] == "runtime_configuration_invalid"
    assert runtime_boundary == []


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
    payload = {"user_id": "attacker", "tenant_id": "attacker", "workspace_root": "/outside"}
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
    assert submitted["completion_mode"] == "business"
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
    from app.application.employee_runtime.agent import restore_codex_employee_gate

    actor, _ = employee
    actor.run("read", workspace_root=str(tmp_path), runtime_context={"turn_id": "turn-1"})
    original = runtime_boundary[0]
    actions, check = restore_codex_employee_gate(
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
    from app.application.employee_runtime.agent import EmployeeAgent, restore_codex_employee_gate

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
        restore_codex_employee_gate(
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
        agent_tools=[business_db_tool_specs()[0]],
        agent_gate=_allow,
        runtime_context=context,
    )
    submitted = runtime_boundary[0]
    assert submitted["runtime_context"]["user_id"] == "41"
    assert submitted["runtime_context"]["turn_id"] == "request-9"
    assert submitted["history"] == history
    assert submitted["input_data"] == {"user_id": "forged"}


def test_canonical_employee_schema_preserves_exact_actions_and_current_gate_identity(
    runtime_boundary,
):
    from app.application.tools.registered_capabilities import (
        build_registered_capability_tool_definition,
    )

    tool = build_registered_capability_tool_definition(allowed_tools={"excel_analysis.read"})
    calls = []

    def gate(name, args, *, runtime_context):
        calls.append((name, deepcopy(args), deepcopy(runtime_context)))
        return {"ok": True}

    _run(tools=[tool], gate=gate, runtime_context={"call_id": "parent-call"})
    submitted = runtime_boundary[0]
    assert submitted["allowed_actions"] == ["excel_analysis.read"]
    check = submitted["gate"]
    context = {
        "run_id": "original-run",
        "task_id": "original-task",
        "call_id": "current-call",
        "employee_id": "clerk",
    }
    assert (
        check(
            "excel_analysis", "read", {"file_path": "public/report.xlsx"}, runtime_context=context
        )["ok"]
        is True
    )
    assert calls == [
        (
            "execute_erp_capability",
            {
                "tool_id": "excel_analysis",
                "action": "read",
                "params": {"file_path": "public/report.xlsx"},
            },
            context,
        )
    ]
    assert (
        check(
            "excel_analysis", "export", {"file_path": "public/report.xlsx"}, runtime_context=context
        )["ok"]
        is False
    )
    assert check("excel_analysis", "read", {}, runtime_context=context)["ok"] is False
    assert len(calls) == 1
    assert context["call_id"] == "current-call"


@pytest.mark.parametrize("change", ["ambiguous", "duplicate", "external_ref"])
def test_canonical_schema_never_widens_branches_or_fetches_references(runtime_boundary, change):
    from app.application.tools.registered_capabilities import (
        build_registered_capability_tool_definition,
    )

    tool = build_registered_capability_tool_definition(allowed_tools={"excel_analysis.read"})
    schema = tool["function"]["parameters"]
    branch = schema["anyOf"][0]
    if change == "ambiguous":
        branch["properties"]["action"]["enum"].append("export")
    elif change == "duplicate":
        schema["anyOf"].append(deepcopy(branch))
    else:
        branch["properties"]["params"] = {"$ref": "https://unauthorized.example/contract.json"}
    result = _run(tools=[tool], gate=_allow)
    if change == "external_ref":
        assert (
            runtime_boundary[0]["gate"]("excel_analysis", "read", {"file_path": "in/report.xlsx"})[
                "ok"
            ]
            is False
        )
    else:
        assert result["error_code"] == "employee_runtime_tools_unsupported"
        assert runtime_boundary == []


def test_restore_uses_original_context_for_tool_projection_and_gate(
    employee, runtime_boundary, monkeypatch
):
    from app.application.employee_runtime.agent import EmployeeAgent, restore_codex_employee_gate

    actor, _ = employee
    actor.run("read", runtime_context={"turn_id": "turn-original", "call_id": "parent"})
    original = runtime_boundary[0]
    seen = []
    build_tools = EmployeeAgent._build_agent_tools
    build_gate = EmployeeAgent._build_agent_gate

    def tools(self, manifest, config, runtime_context=None):
        seen.append(("tools", deepcopy(runtime_context)))
        return build_tools(self, manifest, config, runtime_context)

    def gate(self, manifest, config, workspace, runtime_context=None):
        seen.append(("gate", deepcopy(runtime_context)))
        return build_gate(self, manifest, config, workspace, runtime_context)

    monkeypatch.setattr(EmployeeAgent, "_build_agent_tools", tools)
    monkeypatch.setattr(EmployeeAgent, "_build_agent_gate", gate)
    restore_codex_employee_gate(
        "clerk",
        original["runtime_context"],
        input_data={"user_id": "attacker", "call_id": "forged"},
    )
    assert seen == [("tools", original["runtime_context"]), ("gate", original["runtime_context"])]
