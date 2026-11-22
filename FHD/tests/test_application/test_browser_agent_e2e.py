"""Real approved Agent -> spawned Chromium -> durable owned receipt, then replay.

The existing authority fixtures create SQLite sessions, approvals and artifacts.
Only the synthetic website is a test boundary; the spawned executor is unmodified.
"""

from __future__ import annotations

import hashlib
import json
import time

from app.application.agent_orchestrator import artifact_files
from app.application.agent_orchestrator import business_write_guard as guard
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import ToolCall
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from tests.test_application.test_surface_worker import (
    _claim,
)
from tests.test_application.test_surface_worker import (
    harness as _harness,
)
from tests.test_application.test_surface_worker import (
    sessions as _sessions,
)
from tests.test_application.test_surface_worker import (
    surface as _surface,
)
from tests.test_infrastructure.test_browser_runtime import (
    browser_executable as _browser_executable,
)
from tests.test_infrastructure.test_browser_runtime import (
    playwright_runtime as _playwright_runtime,
)
from tests.test_infrastructure.test_browser_runtime import (
    website as _website,
)

harness, sessions, surface = _harness, _sessions, _surface
browser_executable, playwright_runtime, website = (
    _browser_executable,
    _playwright_runtime,
    _website,
)


def test_approved_agent_spawns_real_browser_and_reuses_durable_receipt(
    surface, sessions, website, browser_executable, monkeypatch
):
    origin, state = website
    monkeypatch.setenv("XCAGI_BROWSER_ALLOWED_ORIGINS", json.dumps({"7": [origin]}))
    if browser_executable:
        monkeypatch.setenv("XCAGI_BROWSER_EXECUTABLE", browser_executable)
    else:
        monkeypatch.delenv("XCAGI_BROWSER_EXECUTABLE", raising=False)
    reference = surface.upload(content=b"approved browser evidence")
    verification = {
        "kind": "text",
        "locator": {"selector": "#receipt"},
        "expected": "receipt-1:Approved agent",
    }
    run, step, context = surface.task(
        params={
            "url": origin,
            "steps": [
                {"action": "fill", "locator": {"label": "Name"}, "value": "Approved agent"},
                {"action": "select", "locator": {"label": "Plan"}, "value": "pro"},
                {"action": "check", "locator": {"label": "Accept"}, "value": True},
                {
                    "action": "upload",
                    "locator": {"label": "Evidence"},
                    "files": [reference],
                },
                {
                    "action": "click",
                    "locator": {"role": "button", "name": "Submit"},
                    "verify": [verification],
                },
                {"action": "download", "locator": {"role": "link", "name": "Download report"}},
            ],
            "verify": [verification],
        }
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=step.params,
        metadata={"idempotency_key": context["idempotency_key"]},
    )
    run.tool_calls.append(call)
    freeze_verification_contract(
        run, step, call, get_tool_action_spec(step.tool_id, step.action), context
    )
    surface.repository.save(run)
    execution = _claim(sessions, run)
    with guard.worker_claim_scope(surface.repository, execution, "surface-worker"):
        result = AgentToolExecutor().execute_with_deadline(
            step, runtime_context=context, deadline_monotonic=time.monotonic() + 60
        )
        assert result.get("success") is True and result["verified"] is True, result
        replay = AgentToolExecutor().execute_with_deadline(
            step, runtime_context=context, deadline_monotonic=time.monotonic() + 60
        )
    assert replay.get("success") is True and replay["verified"] is True, replay
    step.output = call.output = result
    bind_execution_receipt(call)
    for _ in range(2):
        report = verify_step_result(run=run, step=step, call=call, context=context)
        assert report["accepted"] is True, report
        assert report["checks"][-1]["evidence"]["business_effect_verified"] is False
    assert result["run_id"] == replay["run_id"] == run.run_id
    assert result["artifacts"] == replay["artifacts"]
    assert surface.calls == []  # The parent's mocked runtime never supplied the receipt.
    expected = {
        "name": "Approved agent",
        "plan": "pro",
        "accepted": True,
        "filename": "evidence.txt",
    }
    assert state["submissions"] == [expected]  # A second process must not submit again.
    assert all(item["status"] == "completed" for item in result["steps"])
    artifacts = {item["name"]: item for item in result["artifacts"]}
    assert len(artifacts) == 2 and "browser-receipt.json" in artifacts
    for item in artifacts.values():
        content = artifact_files.read_verified_run_file(run.run_id, item)
        assert item["metadata"]["sha256"] == hashlib.sha256(content).hexdigest()
        assert item["metadata"]["owner_user_id"] == "71"
        assert item["metadata"]["tenant_id"] == "7"
        document = json.loads(content)
        if item["name"] == "browser-receipt.json":
            assert document["run_id"] == run.run_id and document["verified"] is True
        else:
            assert document == expected
