"""Optional output paths keep writes outside a read-only output contract."""

from __future__ import annotations

import copy

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.tool_spec import (
    get_tool_action_spec,
    validate_tool_call,
)


@pytest.fixture(params=[("excel_analyzer", "analyze"), ("label_template_generator", "execute")])
def contract(request):
    spec = get_tool_action_spec(*request.param)
    assert spec is not None
    sample = spec.contract_samples[0]
    return spec, copy.deepcopy(sample["input"]), copy.deepcopy(sample["output"])


def _receipt(spec, params, output):
    validation = validate_tool_call(spec.tool_id, spec.action, params)
    assert validation.ok, validation.message
    context = {"tenant_id": "7", "actor_id": "9"}
    step = AgentStep(
        node_id="analyze",
        tool_id=spec.tool_id,
        action=spec.action,
        params=copy.deepcopy(params),
    )
    step.status, step.attempt_count, step.output = "completed", 1, copy.deepcopy(output)
    run = AgentRun(user_id="9", message="Analyze input", steps=[step])
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(params),
        status="completed",
        output=copy.deepcopy(output),
        metadata={"attempt_count": 1},
    )
    run.tool_calls.append(call)
    freeze_verification_contract(run, step, call, spec, context)
    bind_execution_receipt(call)
    return run, step, call, context


@pytest.mark.parametrize("path", [None, "", "/tmp/output", " "])
def test_only_unset_output_paths_can_use_the_read_contract(contract, path):
    spec, params, output = contract
    assert spec.read_only is False
    key = spec.read_only_if_unset[0]
    if path is not None:
        params[key] = path
    # Neither a client argument nor a returned verdict grants read-only authority.
    params["read_only"] = True
    output.update(read_only=True, verification={"verified": True, "read_only": True})
    run, step, call, context = _receipt(spec, params, output)
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["accepted"] is (path in (None, ""))
    assert report["code"] == (
        "read_only_output_contract_checked" if path in (None, "") else "result_verifier_unavailable"
    )
    assert report["status"] != "verified"


def test_changed_parameters_cannot_reuse_a_frozen_read_contract(contract):
    spec, params, output = contract
    run, step, call, context = _receipt(spec, params, output)
    path_key = spec.read_only_if_unset[0]
    step.params[path_key] = call.params[path_key] = "/tmp/new-output"
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["accepted"] is False
    assert report["code"] == "verification_binding_invalid"


@pytest.mark.parametrize("value", [False, 0, [], {}])
def test_invalid_false_values_cannot_select_the_read_contract(contract, value):
    spec, params, _output = contract
    params[spec.read_only_if_unset[0]] = value
    assert not validate_tool_call(spec.tool_id, spec.action, params).ok
    assert spec.is_read_only_call(params) is False
