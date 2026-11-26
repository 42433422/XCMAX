"""Host-verifier fixture for queue/approval tests, not business acceptance."""

import copy

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import ToolCall
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2


def attach_fixture_verified_write(run, monkeypatch):
    step = run.steps[0]
    context = run.metadata["runtime_context"]
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        status="completed",
        output=copy.deepcopy(step.output),
    )
    run.tool_calls.append(call)
    spec = ToolActionSpecV2(
        tool_id=step.tool_id,
        action=step.action,
        output_schema={"type": "object", "required": ["success"]},
    )
    freeze_verification_contract(run, step, call, spec, context)
    bind_execution_receipt(call)
    with monkeypatch.context() as patch:
        patch.setattr(
            "app.application.agent_orchestrator.verification_readback.verify_independent_result",
            lambda **_: {
                "status": "verified",
                "code": "fixture_readback",
                "checks": [
                    {
                        "check_id": "effect",
                        "status": "passed",
                        "source": "transaction_test_fixture",
                        "evidence": {"original_step_id": step.step_id},
                    }
                ],
            },
        )
        report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["accepted"] is True
    return call
