"""Dynamic effects require a local read contract; execution JSON is not proof."""

from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.tools.mcp import registry
from app.application.tools.mcp.verification import can_observe_unknown, registered_contract
from app.infrastructure.mcp.client import McpToolInfo
from app.infrastructure.mcp.config import McpServerConfig


@pytest.fixture
def adapter(monkeypatch):
    definition = {
        "version": 1,
        "read_action": "read_operation",
        "operation_key_param": "operation_id",
        "read_arguments": {"id": "operation_key", "tenant": "tenant_id", "owner": "owner_user_id"},
        "postcondition_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "posted"}},
        },
    }
    config = McpServerConfig(
        name="ledger",
        command="reviewed-adapter",
        read_only_tools=("read_operation",),
        verification={"post": definition},
    )
    infos = [
        McpToolInfo(
            "post",
            "Post",
            {
                "type": "object",
                "required": ["operation_id"],
                "properties": {"operation_id": {"type": "string"}},
            },
            False,
        ),
        McpToolInfo(
            "read_operation",
            "Read original receipt",
            {
                "type": "object",
                "required": ["id", "tenant", "owner"],
                "properties": {key: {"type": "string"} for key in ("id", "tenant", "owner")},
            },
            True,
        ),
    ]
    state = SimpleNamespace(config=config, reads=[], receipt={})
    registry.reset_mcp_cache_for_tests()
    monkeypatch.setattr(registry, "load_server_configs", lambda: [state.config])
    monkeypatch.setattr(registry, "list_tools", lambda _config: infos)
    monkeypatch.setattr(registry, "_register_with_guard", lambda _tools: None)
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope._bound_actor",
        lambda _context: SimpleNamespace(id=9),
    )

    def read(_config, action, arguments, **options):
        assert action == "read_operation", "verification must never dispatch the writer"
        state.reads.append((action, copy.deepcopy(arguments), options))
        return {"success": True, "structured_content": copy.deepcopy(state.receipt)}

    monkeypatch.setattr(registry, "call_tool", read)
    yield state
    registry.reset_mcp_cache_for_tests()


def receipt(adapter, *, unknown=False):
    context = {"tenant_id": "7", "user_id": "9", "actor_id": "9"}
    step = AgentStep(
        node_id="post",
        tool_id="mcp__ledger",
        action="post",
        params={"operation_id": "original-1"},
        attempt_count=1,
    )
    run = AgentRun(
        user_id="9",
        message="Post original",
        steps=[step],
        metadata={"runtime_context": dict(context)},
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=dict(step.params),
        metadata={"attempt_count": 1},
    )
    run.tool_calls.append(call)
    context.update(run_id=run.run_id, step_id=step.step_id, node_id=step.node_id)
    spec = ToolActionSpecV2(tool_id=step.tool_id, action=step.action)
    freeze_verification_contract(run, step, call, spec, context)
    call.output = {"success": True, "verified": True}
    if unknown:
        call.output = {
            "success": False,
            "outcome": "unknown",
            "error_code": "transport_lost",
            "retryable": False,
        }
    step.output = copy.deepcopy(call.output)
    call.status = step.status = "failed" if unknown else "completed"
    bind_execution_receipt(call)
    adapter.receipt = {
        "operation_key": "original-1",
        "tenant_id": "7",
        "owner_user_id": "9",
        "input_sha256": canonical_hash(step.params),
        "operation_state": "completed",
        "effect": {"status": "posted"},
    }
    return run, step, call, context


def test_dynamic_readback_uses_original_identity_and_independent_read(adapter):
    run, step, call, context = receipt(adapter)
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["accepted"] is True
    assert result["checks"][0]["evidence"]["business_effect_verified"] is True
    assert adapter.reads == [
        ("read_operation", {"id": "original-1", "tenant": "7", "owner": "9"}, {"retry_safe": True})
    ]


@pytest.mark.parametrize("field", ["operation_key", "tenant_id", "owner_user_id", "input_sha256"])
def test_cross_scope_or_different_request_is_rejected(adapter, field):
    run, step, call, context = receipt(adapter)
    adapter.receipt[field] = "other"
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert not result["accepted"]
    assert result["code"] == "mcp_verification_identity_mismatch"


def test_writer_claim_and_unmet_postcondition_cannot_verify(adapter):
    run, step, call, context = receipt(adapter)
    adapter.receipt["effect"]["status"] = "draft"
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "mcp_postcondition_mismatch"
    assert not result["accepted"]


def test_changed_config_blocks_old_contract_without_a_read(adapter):
    run, step, call, context = receipt(adapter)
    adapter.config = replace(adapter.config, command="different-server")
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "mcp_verification_contract_changed"
    assert not adapter.reads


def test_unknown_effect_can_be_observed_but_never_replayed_or_settled(adapter):
    run, step, call, context = receipt(adapter, unknown=True)
    original = copy.deepcopy(call.output)
    assert can_observe_unknown(run, step, call)
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "original_execution_unsettled"
    assert not result["accepted"]
    assert result["checks"][0]["evidence"]["business_effect_verified"] is True
    assert call.output == original
    assert len(adapter.reads) == 1


def test_unreviewed_reader_and_missing_contract_do_not_admit_writes(adapter, monkeypatch):
    run, step, call, context = receipt(adapter)
    adapter.config = replace(adapter.config, read_only_tools=())
    tools, _ = registry._snapshot()
    actions = tools["mcp__ledger"]["actions"]
    assert registered_contract(adapter.config, actions, "post") is None
    assert actions["post"]["result_verification"]["status"] == "unavailable"
    monkeypatch.setattr(
        "app.application.tools.surface_authority.require_surface_authority",
        lambda *a, **k: (SimpleNamespace(id=9), run),
    )
    result = registry.call_mcp_tool(step.tool_id, step.action, step.params, runtime_context=context)
    assert result["execution_status"] == "not_started"
    assert result["error_code"] == "mcp_result_verifier_required"
    assert not adapter.reads


def test_current_approved_write_with_frozen_contract_is_admitted(adapter, monkeypatch):
    run, step, call, context = receipt(adapter)
    monkeypatch.setattr(
        "app.application.tools.surface_authority.require_surface_authority",
        lambda *a, **k: (SimpleNamespace(id=9), run),
    )
    writes = []

    def write(_config, action, arguments, **options):
        writes.append((action, arguments, options))
        return {"success": True}

    monkeypatch.setattr(registry, "call_tool", write)
    assert registry.call_mcp_tool(step.tool_id, step.action, step.params, runtime_context=context)[
        "success"
    ]
    assert writes == [("post", {"operation_id": "original-1"}, {"retry_safe": False})]
    call.metadata["verification_contract"]["input_sha256"] = "tampered"
    rejected = registry.call_mcp_tool(
        step.tool_id, step.action, step.params, runtime_context=context
    )
    assert rejected["execution_status"] == "not_started"
    assert len(writes) == 1


@pytest.mark.parametrize("changed", ["config", "read_schema", "write_schema"])
def test_write_checks_the_contract_of_the_snapshot_actually_dispatched(
    adapter, monkeypatch, changed
):
    run, step, _call, context = receipt(adapter)
    original_tools, original_servers = registry._snapshot()
    selected_tools, selected_servers = copy.deepcopy(original_tools), dict(original_servers)
    if changed == "config":
        selected_servers[step.tool_id] = replace(adapter.config, command="unapproved-adapter")
    else:
        action = "read_operation" if changed == "read_schema" else "post"
        selected_tools[step.tool_id]["actions"][action]["input_schema"]["properties"][
            "new_optional_field"
        ] = {"type": "string"}
    snapshots = 0

    def changed_between_checks():
        nonlocal snapshots
        snapshots += 1
        if snapshots == 1:
            return selected_tools, selected_servers
        return original_tools, original_servers

    monkeypatch.setattr(registry, "_snapshot", changed_between_checks)
    monkeypatch.setattr(
        "app.application.tools.surface_authority.require_surface_authority",
        lambda *a, **k: (SimpleNamespace(id=9), run),
    )
    monkeypatch.setattr(
        registry, "call_tool", lambda *a, **k: pytest.fail("unapproved snapshot reached writer")
    )
    rejected = registry.call_mcp_tool(
        step.tool_id, step.action, step.params, runtime_context=context
    )
    assert rejected["error_code"] == "mcp_result_verifier_required"
    assert rejected["execution_status"] == "not_started"
    assert snapshots >= 2


def test_read_argument_mismatch_blocks_write_before_effect(adapter, monkeypatch):
    definition = copy.deepcopy(adapter.config.verification)
    definition["post"]["read_arguments"]["wrong_id"] = definition["post"]["read_arguments"].pop(
        "id"
    )
    adapter.config = replace(adapter.config, verification=definition)
    run, step, call, context = receipt(adapter)
    assert call.metadata["verification_contract"].get("mcp_acceptance") is None
    monkeypatch.setattr(
        "app.application.tools.surface_authority.require_surface_authority",
        lambda *a, **k: (SimpleNamespace(id=9), run),
    )
    rejected = registry.call_mcp_tool(
        step.tool_id, step.action, step.params, runtime_context=context
    )
    assert rejected["error_code"] == "mcp_result_verifier_required"
    assert rejected["execution_status"] == "not_started"
    assert not adapter.reads


@pytest.mark.parametrize("reference", ["https://untrusted.invalid/schema.json", "#/missing"])
def test_unresolvable_postcondition_reference_cannot_enable_write(adapter, reference):
    definition = copy.deepcopy(adapter.config.verification)
    definition["post"]["postcondition_schema"]["properties"]["status"] = {"$ref": reference}
    adapter.config = replace(adapter.config, verification=definition)
    tools, _ = registry._snapshot()
    assert tools["mcp__ledger"]["actions"]["post"]["result_verification"]["status"] == "unavailable"
    _run, _step, call, _context = receipt(adapter)
    assert call.metadata["verification_contract"].get("mcp_acceptance") is None
    assert not adapter.reads


def test_valid_local_postcondition_definition_can_verify_original_effect(adapter):
    definition = copy.deepcopy(adapter.config.verification)
    schema = definition["post"]["postcondition_schema"]
    schema["$defs"] = {"posted_status": {"const": "posted"}}
    schema["properties"]["status"] = {"$ref": "#/$defs/posted_status"}
    adapter.config = replace(adapter.config, verification=definition)
    run, step, call, context = receipt(adapter)
    assert call.metadata["verification_contract"]["mcp_acceptance"] is not None
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["accepted"] is True
    assert len(adapter.reads) == 1


def test_readback_checks_the_reader_schema_of_the_final_dispatch_snapshot(adapter, monkeypatch):
    run, step, call, context = receipt(adapter)
    original_tools, original_servers = registry._snapshot()
    changed_tools = copy.deepcopy(original_tools)
    changed_tools[step.tool_id]["actions"]["read_operation"]["input_schema"]["properties"][
        "new_optional_field"
    ] = {"type": "string"}
    original_call = registry.call_mcp_tool

    def change_schema_at_dispatch(*args, **kwargs):
        # Preparation and permission checks saw the frozen contract. The actual
        # transport entry now sees a new schema at the same configured server.
        monkeypatch.setattr(registry, "_snapshot", lambda: (changed_tools, original_servers))
        return original_call(*args, **kwargs)

    monkeypatch.setattr(registry, "call_mcp_tool", change_schema_at_dispatch)
    monkeypatch.setattr(
        registry, "call_tool", lambda *a, **k: pytest.fail("changed reader reached the remote")
    )
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert not result["accepted"]
    assert result["code"] == "mcp_verification_source_unavailable"
    assert not adapter.reads


def test_revoked_read_permission_blocks_independent_observation(adapter, monkeypatch):
    run, step, call, context = receipt(adapter)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_permission.actor_tool_denial",
        lambda *a, **k: {"error_code": "tool_permission_denied"},
    )
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "mcp_verification_read_permission_denied"
    assert not adapter.reads


def test_reverify_unknown_original_keeps_queue_effect_and_receipt(adapter, monkeypatch):
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.verification_recovery import (
        reverify_run,
        verification_report,
    )

    run, step, call, context = receipt(adapter, unknown=True)
    run.status = "failed"
    repo, queue = InMemoryAgentRunRepository(), InMemoryTaskExecutionRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.task_execution_repository.get_task_execution_repository",
        lambda: queue,
    )
    repo.save(run)
    queue.enqueue(run)
    queue.claim("original", lease_seconds=60)
    queue.mark_open_effect(run.run_id)
    queue.finish(run.run_id, "original", "failed", error_code="needs_verification")
    stopped = queue.get(run.run_id).to_dict()
    result = reverify_run(repo, run.run_id)
    assert not verification_report(result)["accepted"]
    assert result.tool_calls[0].output == call.output
    assert result.tool_calls[0].metadata["verification"]["code"] == "original_execution_unsettled"
    assert queue.get(run.run_id).to_dict() == stopped
    assert len(adapter.reads) == 1
