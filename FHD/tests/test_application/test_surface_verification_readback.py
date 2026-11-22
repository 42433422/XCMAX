"""Surface completion uses original host records or a separate, bounded read port."""

from __future__ import annotations

import copy
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.artifact_files import artifact_path
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.agent_orchestrator.verification_surface import execution_surface_binding
from app.application.computer_use import ComputerUseService
from app.application.tools.browser import _persist_artifacts
from app.domain.browser_contract import BrowserExecute
from app.domain.browser_receipt import evidence_hash, observed_assertion
from app.infrastructure.mcp.config import McpServerConfig
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def owner(trusted_actor, monkeypatch, tmp_path):
    actor = trusted_actor(role="admin")
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setenv("XCAGI_COMPUTER_USE_USER_ID", str(actor.user_id))
    monkeypatch.setenv("XCAGI_COMPUTER_USE_TENANT_ID", str(actor.tenant_id))
    return actor


def case(owner, tool="browser", action="execute", params=None):
    if params is None:
        params = {
            "url": "https://example.test/form",
            "steps": [{"action": "click", "locator": {"text": "Save"}}],
            "verify": [
                {"kind": "text", "locator": {"selector": "#result"}, "expected": "Saved #42"}
            ],
        }
    step = AgentStep(
        node_id="surface",
        tool_id=tool,
        action=action,
        params=copy.deepcopy(params),
        status="running",
        attempt_count=1,
    )
    run = AgentRun(
        user_id=str(owner.user_id),
        message="Observe the requested surface result",
        steps=[step],
        metadata={"runtime_context": copy.deepcopy(owner.context)},
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=tool,
        action=action,
        params=copy.deepcopy(params),
        metadata={"attempt_count": 1},
    )
    run.tool_calls.append(call)
    context = {
        **owner.context,
        **task_execution_context(run, step),
        "run_id": run.run_id,
        "step_id": step.step_id,
    }
    call.metadata["idempotency_key"] = context["idempotency_key"]
    spec = ToolActionSpecV2(
        tool_id=tool,
        action=action,
        output_schema={
            "type": "object",
            "required": ["success"],
            "properties": {"success": {"type": "boolean"}},
        },
    )
    freeze_verification_contract(run, step, call, spec, context)
    return SimpleNamespace(run=run, step=step, call=call, context=context, spec=spec)


def complete(item, output):
    item.step.output = copy.deepcopy(output)
    item.call.output = copy.deepcopy(output)
    item.step.status = item.call.status = "completed"
    bind_execution_receipt(item.call)


def verify(item):
    return verify_step_result(run=item.run, step=item.step, call=item.call, context=item.context)


def native_browser(item, tmp_path, *, actual="Saved #42", binding=True):
    plan = BrowserExecute.model_validate(item.step.params).model_dump(exclude_none=True)
    content = b"requested artifact bytes\n"
    download = tmp_path / "download.txt"
    download.write_bytes(content)
    import hashlib

    output = {
        "success": True,
        "verified": True,
        "outcome": "succeeded",
        "run_id": item.run.run_id,
        "steps": [{"index": 0, "action": "click", "status": "completed", "verification": []}],
        "verification": [observed_assertion(plan["verify"][0], actual)],
        "artifacts": [
            {
                "name": download.name,
                "path": str(download),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    _persist_artifacts(
        output,
        tmp_path,
        item.run.run_id,
        int(item.context["user_id"]),
        str(item.context["tenant_id"]),
        execution_surface_binding(item.run, item.step.params, item.context) if binding else {},
    )
    complete(item, output)


def test_native_browser_records_and_downloads_are_independently_read(owner, tmp_path, monkeypatch):
    item = case(owner)
    native_browser(item, tmp_path)
    original = copy.deepcopy(item.call.output)
    monkeypatch.setattr(
        "app.application.tools.browser.execute_browser",
        lambda *_a, **_kw: pytest.fail("verification replayed input"),
    )
    for _ in range(2):
        report = verify(item)
        assert report["status"] == "verified", report
        assert sum(check["source"] == "run_artifact" for check in report["checks"]) == 2
        scope = report["checks"][-1]["evidence"]
        assert scope["verification_scope"] == "recorded_dom_assertions"
        assert (
            scope["current_state_verified"] is False and scope["business_effect_verified"] is False
        )
        assert item.call.output == original


@pytest.mark.parametrize(
    "change",
    [
        "no_binding",
        "different_observation",
        "file_changed",
        "file_missing",
        "tenant_changed",
        "params_changed",
        "mod_changed",
    ],
)
def test_native_browser_claimed_success_cannot_replace_original_evidence(owner, tmp_path, change):
    item = case(owner)
    native_browser(
        item,
        tmp_path,
        actual="Still pending" if change == "different_observation" else "Saved #42",
        binding=change != "no_binding",
    )
    if change == "file_changed":
        artifact_path(item.run.run_id, item.call.output["artifacts"][0]["artifact_id"]).write_bytes(
            b"replaced"
        )
    elif change == "file_missing":
        artifact_path(item.run.run_id, item.call.output["artifacts"][0]["artifact_id"]).unlink()
    elif change == "tenant_changed":
        item.context["tenant_id"] = str(int(item.context["tenant_id"]) + 1)
    elif change == "mod_changed":
        item.context["mod_id"] = "foreign-mod"
    elif change == "params_changed":
        item.call.params["verify"][0]["expected"] = "Different"
        item.step.params = copy.deepcopy(item.call.params)
    assert not verify(item)["accepted"]


@pytest.mark.parametrize("target", ["browser", "desktop"])
@pytest.mark.parametrize("matched", [False, True])
def test_computer_effect_reads_actual_assertion_or_pixel_values(
    owner, target, matched, monkeypatch
):
    assertion = (
        {"kind": "url", "expected": "https://example.test/"}
        if target == "browser"
        else {"pixels": [{"x": 1, "y": 2, "rgb": [20, 30, 40], "tolerance": 2}]}
    )
    params = {
        "request_id": "effect-1",
        "target": target,
        "steps": [{"action": "navigate", "url": "https://example.test/"}]
        if target == "browser"
        else [{"action": "click", "x": 1, "y": 2}],
        "verification": assertion,
    }
    item = case(owner, "desktop_automation", "computer_execute", params)
    observation = (
        observed_assertion(
            assertion, "https://example.test/" if matched else "https://example.test/no"
        )
        if target == "browser"
        else {
            "scope": "visual_pixels",
            "checks": [True],
            "actual_pixels": [[21, 30, 40] if matched else [255, 255, 255]],
            "observed_at": time.time(),
        }
    )
    output = {
        "success": True,
        "verified": True,
        "steps_completed": 1,
        "request_id": "effect-1",
        "verification": observation,
    }
    service = ComputerUseService()
    service._write(
        service._path(service._owner(item.context), "effect", "effect-1"),
        {
            "state": "finished",
            "run_id": item.run.run_id,
            "step_id": item.step.step_id,
            "fingerprint": evidence_hash(params),
            "binding": execution_surface_binding(item.run, params, item.context),
            "result": output,
        },
    )
    complete(item, output)
    monkeypatch.setattr(
        ComputerUseService,
        "invoke",
        lambda *_a, **_kw: pytest.fail("readback replayed physical input"),
    )
    report = verify(item)
    assert report["accepted"] is matched, report
    if matched:
        assert report["checks"][0]["evidence"]["business_effect_verified"] is False


@pytest.fixture
def mcp_config(monkeypatch):
    from app.application.agent_orchestrator.tool_spec import invalidate_tool_specs_cache
    from app.application.tools.mcp import registry
    from app.infrastructure.mcp.client import McpToolInfo

    config = McpServerConfig(
        name="browser",
        command="node",
        browser=True,
        session_mode="persistent",
        read_only_tools=("browser_snapshot",),
    )
    actions = {
        name: registry._action_spec(
            McpToolInfo(
                name, "Fixture browser action", {"type": "object"}, name == "browser_snapshot"
            ),
            config,
        )
        for name in ("browser_navigate", "browser_click", "browser_snapshot")
    }
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "1")
    monkeypatch.setattr(
        registry,
        "_snapshot",
        lambda *a, **k: ({"mcp__browser": {"actions": actions}}, {"mcp__browser": config}),
    )
    invalidate_tool_specs_cache()
    yield config
    invalidate_tool_specs_cache()


@pytest.fixture
def mcp_navigation(owner, mcp_config):
    params = {
        "url": "https://example.test/",
        "verification": {"kind": "url", "expected": "https://example.test/"},
    }
    item = case(owner, "mcp__browser", "browser_navigate", params)
    acceptance = item.call.metadata["verification_contract"]["surface_acceptance"]
    assert acceptance["scope"] == "live_page_assertion"
    assert acceptance["assertion"] == params["verification"]
    return item


@pytest.mark.parametrize(
    "change", ["none", "different_session", "different_url", "lost", "stale", "code_echo"]
)
def test_mcp_postcondition_uses_new_same_session_snapshot(mcp_navigation, monkeypatch, change):
    item = mcp_navigation
    complete(
        item, {"success": True, "server": "browser", "session_id": "generation-1", "verified": True}
    )
    observed = {
        "success": True,
        "session_id": "generation-1",
        "observed_at": time.time(),
        "content": "### Page\n- Page URL: https://example.test/\n### Snapshot\n```yaml\n- button Save\n```",
    }
    if change == "different_session":
        observed["session_id"] = "generation-2"
    if change == "different_url":
        observed["content"] = observed["content"].replace("example.test/", "example.test/wrong")
    if change == "lost":
        observed = {"success": False, "error_code": "mcp_session_lost"}
    if change == "stale":
        observed["observed_at"] = 1
    if change == "code_echo":
        observed["content"] = (
            "### Ran Playwright code\n```js\n### Page\n- Page URL: https://example.test/\n```\n### Snapshot\n```yaml\n- generic Pending\n```"
        )
    calls = []

    def probe(run, step, call, context, config):
        calls.append((run.run_id, step.step_id, call.call_id))
        return copy.deepcopy(observed)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.read_browser_snapshot", probe
    )
    report = verify(item)
    assert report["accepted"] is (change == "none"), report
    assert calls == [(item.run.run_id, item.step.step_id, item.call.call_id)]
    expected_code = {
        "none": "result_verified",
        "different_session": "result_surface_readback_unavailable",
        "different_url": "result_surface_postcondition_unmet",
        "lost": "result_surface_readback_unavailable",
        "stale": "result_surface_readback_unavailable",
        "code_echo": "result_surface_postcondition_unmet",
    }
    assert report["code"] == expected_code[change]


def test_mcp_click_without_frozen_postcondition_remains_inconclusive(
    owner, mcp_config, monkeypatch
):
    item = case(owner, "mcp__browser", "browser_click", {"target": "e1"})
    complete(item, {"success": True, "server": "browser", "session_id": "generation-1"})
    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.read_browser_snapshot",
        lambda *_a: pytest.fail("missing contract must not probe"),
    )
    assert verify(item)["code"] == "result_surface_contract_unavailable"


@pytest.mark.parametrize(
    "change", ["none", "different_session", "missing_check", "failed_check", "reused_request"]
)
def test_aiopen_readback_only_verifies_current_owned_field(owner, monkeypatch, change):
    item = case(
        owner,
        "aiopen",
        "ui_type",
        {"selector": "#name", "text": "new value", "session_id": "owned-screen"},
    )
    complete(item, {"success": True, "session_id": "owned-screen", "request_id": "write-1"})
    observed = {
        "success": True,
        "session_id": "owned-screen",
        "request_id": "read-2",
        "observed_at": time.time(),
        "checks": [{"check": "元素存在", "ok": True}, {"check": "控件值", "ok": True}],
    }
    if change == "different_session":
        observed["session_id"] = "foreign"
    if change == "missing_check":
        observed["checks"].pop()
    if change == "failed_check":
        observed["checks"][-1]["ok"] = False
    if change == "reused_request":
        observed["request_id"] = "write-1"
    seen = []

    def probe(params, context):
        seen.append(copy.deepcopy(params))
        return observed

    monkeypatch.setattr("app.application.aiopen.agent_bridge.read_aiopen_postcondition", probe)
    report = verify(item)
    assert report["accepted"] is (change == "none"), report
    assert seen == [{"selector": "#name", "session_id": "owned-screen", "value": "new value"}]
    assert "new value" not in str(report["checks"])


def test_missing_browser_worker_is_not_recreated_for_verification(mcp_navigation, monkeypatch):
    from app.application.agent_orchestrator import browser_tool_process as processes

    item = mcp_navigation
    complete(item, {"success": True, "server": "browser", "session_id": "lost-generation"})
    monkeypatch.setattr(processes, "_WORKERS", {})
    monkeypatch.setattr(
        processes,
        "_BrowserWorker",
        lambda *_a: pytest.fail("readback created a replacement browser"),
    )
    assert verify(item)["code"] == "result_surface_readback_unavailable"


@pytest.mark.parametrize(
    "change", ["none", "wrong_call", "wrong_contract", "wrong_session", "changed_params"]
)
def test_existing_worker_read_port_accepts_only_original_contract(
    mcp_navigation, monkeypatch, change
):
    from app.application.agent_orchestrator.browser_tool_process import _BrowserReadbackExecutor
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.tools.mcp import registry

    item = mcp_navigation
    complete(item, {"success": True, "server": "browser", "session_id": "generation-1"})
    repository = InMemoryAgentRunRepository()
    repository.save(item.run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    request = {
        "call_id": item.call.call_id,
        "contract_sha256": item.call.metadata["verification_contract"]["contract_sha256"],
        "session_id": "generation-1",
    }
    if change == "wrong_call":
        request["call_id"] = "other-call"
    if change == "wrong_contract":
        request["contract_sha256"] = "0" * 64
    if change == "wrong_session":
        request["session_id"] = "other-generation"
    if change == "changed_params":
        item.step.params["url"] = "https://example.test/foreign"
    reads = []

    def read(tool, action, params, *, runtime_context):
        reads.append((tool, action, params))
        assert runtime_context["node_outputs"][item.step.node_id]["session_id"] == "generation-1"
        return {"success": True, "session_id": "generation-1", "content": "actual observation"}

    monkeypatch.setattr(registry, "call_mcp_tool", read)
    result = _BrowserReadbackExecutor().execute(
        item.step, runtime_context={**item.context, "_surface_readback": request}
    )
    assert result["success"] is (change == "none")
    assert reads == ([("mcp__browser", "browser_snapshot", {})] if change == "none" else [])


def test_current_permission_loss_never_invokes_surface_probe(mcp_navigation, monkeypatch):
    item = mcp_navigation
    complete(item, {"success": True, "server": "browser", "session_id": "generation-1"})
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_permission.actor_tool_denial",
        lambda *_a, **_k: {"error": "revoked"},
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.read_browser_snapshot",
        lambda *_a: pytest.fail("permission loss must stop the read port"),
    )
    assert verify(item)["code"] == "result_read_permission_unavailable"
