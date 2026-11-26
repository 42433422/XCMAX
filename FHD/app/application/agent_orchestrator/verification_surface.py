"""Read existing surface receipts and bounded live probes under a frozen contract.

These checks prove their stated DOM/pixel/file scope. They never turn a browser
acknowledgement into proof of an external business transaction.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.verification_readback import _report
from app.domain.autonomy.browser_policy import BROWSER_ACTIONS, BROWSER_OBSERVATIONS
from app.domain.browser_receipt import assertion_value, evidence_hash
from app.utils.operational_errors import RECOVERABLE_ERRORS

_NATIVE = frozenset(
    {("browser", "observe"), ("browser", "execute"), ("desktop_automation", "computer_execute")}
)
_MAX_BYTES = 25 * 1024 * 1024
_SCREEN_WRITES = frozenset(
    {"ui_navigate", "ui_click", "ui_type", "ui_select", "ui_upload", "ui_scroll"}
)


def supports_surface_verification(tool_id: str, action: str) -> bool:
    return (
        (tool_id, action) in _NATIVE
        or (tool_id == "aiopen" and action in _SCREEN_WRITES)
        or (tool_id.startswith("mcp__") and action in BROWSER_ACTIONS - BROWSER_OBSERVATIONS)
    )


def capture_surface_acceptance(run: Any, step: Any, context: dict) -> dict:
    """Only the host's registered action semantics choose the evidence scope."""
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.domain.browser_contract import BrowserExecute, BrowserObserve

    acceptance: dict[str, Any] = {
        "request_id": task_execution_context(run, step)["idempotency_key"],
        "frozen_at": time.time(),
        "business_effect_verified": False,
        "current_state_verified": False,
    }
    try:
        if step.tool_id == "aiopen":
            from app.application.aiopen.agent_bridge import downstream_verification

            condition = downstream_verification(
                run, step.params, {**context, "step_id": step.step_id}
            )
            params = copy.deepcopy(condition.get("params") or {})
            target = {
                key: step.params[key]
                for key in ("session_id", "ref", "selector")
                if key in step.params
            }
            if step.action == "ui_type" and (target.get("ref") or target.get("selector")):
                params = {**target, "value": step.params["text"]}
            elif (
                step.action == "ui_select"
                and "value" in step.params
                and (target.get("ref") or target.get("selector"))
            ):
                params = {**target, "value": step.params["value"]}
            elif step.action == "ui_navigate":
                params = {
                    "session_id": step.params.get("session_id"),
                    "url_contains": step.params["path"],
                }
            if not params.get("session_id") or not any(
                params.get(key) for key in ("ref", "selector", "text", "url_contains")
            ):
                raise ValueError("screen action has no concrete postcondition")
            acceptance.update(
                scope="live_dom_assertions", assertion=params, current_state_verified=True
            )
            if step.action in {"ui_click", "ui_upload"}:
                from app.application.aiopen.agent_bridge import read_aiopen_postcondition

                before = read_aiopen_postcondition(copy.deepcopy(params), context)
                if not _screen_checks_match(before, params, passed=False):
                    raise ValueError("screen postcondition is already present or unavailable")
                acceptance["before_observation_sha256"] = evidence_hash(before["checks"])
        elif step.tool_id.startswith("mcp__"):
            acceptance.update(_mcp_action_acceptance(run, step, context))
        elif step.tool_id == "browser":
            model = BrowserExecute if step.action == "execute" else BrowserObserve
            plan = model.model_validate(step.params).model_dump(exclude_none=True)
            acceptance.update(
                scope="recorded_dom_assertions"
                if step.action == "execute"
                else "recorded_page_observation",
                assertions=plan.get("verify", []),
                steps=[
                    {"action": item["action"], "assertions": item["verify"]}
                    for item in plan.get("steps", [])
                ],
            )
        else:
            verification = copy.deepcopy(step.params.get("verification"))
            if step.params.get("target") == "browser":
                from app.desktop_automation.computer_browser import BrowserVerification

                verification = BrowserVerification.model_validate(verification).model_dump(
                    exclude_none=True
                )
            acceptance.update(
                scope="recorded_visual_pixels"
                if step.params.get("target") == "desktop"
                else "recorded_dom_assertions",
                assertion=verification,
                effect_request_id=step.params.get("request_id"),
            )
    except (TypeError, PermissionError) + RECOVERABLE_ERRORS:
        acceptance["scope"] = "unavailable"
    return acceptance


def _mcp_action_acceptance(run: Any, step: Any, context: dict) -> dict:
    """Freeze one Xiaox-selected action against original, current page evidence."""
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.browser_tool_process import read_browser_snapshot
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.tools.mcp.registry import browser_server_config, mcp_session_scope
    from app.domain.autonomy.browser_evidence import (
        BROWSER_POSTCONDITION_SCHEMA,
        snapshot_text,
        targets_observed,
    )
    from app.infrastructure.xiaox.receipts import browser_action_receipts

    config = browser_server_config(step.tool_id)
    scope = mcp_session_scope({**context, "run_id": run.run_id})
    condition = copy.deepcopy(step.params.get("verification"))
    if (
        config is None
        or not scope
        or not Draft202012Validator(BROWSER_POSTCONDITION_SCHEMA).is_valid(condition)
    ):
        raise ValueError("original browser contract unavailable")
    if step.action == "browser_navigate":
        if condition["kind"] != "url" or condition["expected"] != step.params.get("url"):
            raise ValueError("navigation must verify its exact target URL")
    else:
        records = browser_action_receipts({**context, "run_id": run.run_id}, step.tool_id)
        previous = records[-1] if records else None
        if (
            condition["kind"] != "text"
            or previous is None
            or previous["step"].action != "browser_snapshot"
            or condition.get("observation_call_id") not in previous["call_ids"]
        ):
            raise ValueError("action requires the latest original page observation")
        child, observed_step, call = previous["child"], previous["step"], previous["record"]
        observed_context = {
            **copy.deepcopy(child.metadata.get("runtime_context") or {}),
            **task_execution_context(child, observed_step),
            "run_id": child.run_id,
            "step_id": observed_step.step_id,
            "node_id": observed_step.node_id,
            "call_id": call.call_id,
            "input_sha256": (call.metadata.get("verification_contract") or {}).get("input_sha256"),
            "node_outputs": {item.node_id: item.output for item in child.steps},
        }
        observed_at = time.time()
        before = read_browser_snapshot(child, observed_step, call, observed_context, config)
        snapshot = snapshot_text(before)
        if (
            before.get("success") is not True
            or not call.output.get("session_id")
            or before.get("session_id") != call.output["session_id"]
            or type(before.get("observed_at")) not in {int, float}
            or not observed_at <= before["observed_at"] <= time.time() + 5
            or not snapshot
            or not targets_observed(step.params, snapshot)
            or condition["expected"] in snapshot
        ):
            raise ValueError("page changed, target absent or postcondition already present")
        condition.update(
            before_snapshot_sha256=evidence_hash(snapshot),
            before_run_id=child.run_id,
            before_call_id=call.call_id,
            session_id=call.output["session_id"],
        )
    return {
        "scope": "live_page_assertion",
        "assertion": condition,
        "config_sha256": canonical_hash(asdict(config)),
        "session_scope": scope,
        "current_state_verified": True,
    }


def _binding(contract: dict) -> dict:
    return {
        key: copy.deepcopy(contract.get(key))
        for key in (
            "contract_sha256",
            "scope",
            "step_id",
            "node_id",
            "call_id",
            "attempt",
            "tool_id",
            "action",
            "input_sha256",
        )
    }


def execution_surface_binding(run: Any, params: dict, context: dict) -> dict:
    """Read the original persisted host contract, never an executor-supplied proof."""
    call = next(
        (
            item
            for item in reversed(getattr(run, "tool_calls", ()))
            if item.step_id == context.get("step_id")
        ),
        None,
    )
    if call is None or call.params != params:
        return {}
    contract = call.metadata.get("verification_contract") or {}
    content = {key: value for key, value in contract.items() if key != "contract_sha256"}
    scope = contract.get("scope") or {}
    if (
        contract.get("contract_sha256") != canonical_hash(content)
        or contract.get("input_sha256") != canonical_hash(params)
        or scope.get("run_id") != run.run_id
        or str(scope.get("actor_id")) != str(context.get("user_id"))
        or str(scope.get("tenant_id")) != str(context.get("tenant_id"))
    ):
        return {}
    return _binding(contract)


def _assertion_matches(expected: dict, actual: dict, frozen_at: float) -> bool:
    return bool(
        isinstance(actual, dict)
        and actual.get("status") == "passed"
        and actual.get("kind") == expected["kind"]
        and actual.get("assertion_sha256") == evidence_hash(expected)
        and actual.get("observed_sha256")
        == actual.get("expected_sha256")
        == evidence_hash(assertion_value(expected["kind"], expected.get("expected")))
        and type(actual.get("observed_at")) in {int, float}
        and frozen_at <= actual["observed_at"] <= time.time() + 5
    )


def _assertions_match(expected: list, actual: Any, frozen_at: float) -> bool:
    return (
        isinstance(actual, list)
        and len(expected) == len(actual)
        and all(
            _assertion_matches(check, observed, frozen_at)
            for check, observed in zip(expected, actual)
        )
    )


def _artifact_checks(run: Any, call: Any, output: dict, context: dict) -> tuple[list, dict, dict]:
    from app.application.agent_orchestrator.artifact_files import (
        artifact_path,
        read_verified_run_file,
    )

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        raise ValueError("missing original surface artifacts")
    checks, receipts = [], []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("artifact_type") != "file":
            raise ValueError("invalid surface artifact")
        identity = artifact.get("artifact_id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("invalid surface artifact identity")
        metadata = artifact.get("metadata") or {}
        if (
            any(
                str(metadata.get(field)) != str(value)
                for field, value in {
                    "run_id": run.run_id,
                    "owner_user_id": context["user_id"],
                    "tenant_id": context["tenant_id"],
                    "call_id": call.call_id,
                    "step_id": call.step_id,
                    "params_sha256": canonical_hash(call.params),
                }.items()
            )
            or artifact.get("uri") != f"/api/agent/runs/{run.run_id}/artifacts/{identity}"
        ):
            raise ValueError("surface artifact scope changed")
        if artifact_path(run.run_id, identity).stat().st_size > _MAX_BYTES:
            raise ValueError("surface artifact is too large")
        content = read_verified_run_file(run.run_id, artifact)
        checks.extend(
            _report(
                "verified",
                "result_verified",
                "run_artifact",
                artifact_id=identity,
                sha256=metadata["sha256"],
                size_bytes=len(content),
                verification_scope="artifact_integrity",
                business_effect_verified=False,
            )["checks"]
        )
        if artifact.get("name") == "browser-receipt.json":
            receipts.append((json.loads(content), artifact))
    if len(receipts) != 1:
        raise ValueError("ambiguous browser receipt")
    receipt, artifact = receipts[0]
    return checks, receipt, artifact


def _browser(run: Any, step: Any, call: Any, output: dict, context: dict, contract: dict) -> dict:
    checks, receipt, receipt_artifact = _artifact_checks(run, call, output, context)
    acceptance = contract["surface_acceptance"]
    frozen_at = acceptance["frozen_at"]
    if (
        receipt.get("binding") != _binding(contract)
        or receipt.get("success") is not True
        or receipt.get("run_id") != run.run_id
        or receipt.get("artifacts")
        != [item for item in output["artifacts"] if item != receipt_artifact]
    ):
        return _report("failed", "result_surface_binding_mismatch", "surface_receipt")
    if step.action == "execute":
        expected_steps, actual_steps = acceptance["steps"], receipt.get("steps")
        if (
            not acceptance["assertions"]
            or not _assertions_match(
                acceptance["assertions"], receipt.get("verification"), frozen_at
            )
            or not isinstance(actual_steps, list)
            or len(expected_steps) != len(actual_steps)
            or any(
                actual.get("index") != index
                or actual.get("action") != expected["action"]
                or actual.get("status") != "completed"
                or not _assertions_match(
                    expected["assertions"], actual.get("verification"), frozen_at
                )
                for index, (expected, actual) in enumerate(zip(expected_steps, actual_steps))
            )
        ):
            return _report(
                "inconclusive", "result_surface_assertion_unavailable", "surface_receipt"
            )
    elif receipt.get("snapshot_sha256") != evidence_hash(output.get("snapshot")):
        return _report("failed", "result_surface_observation_mismatch", "surface_receipt")
    checks.extend(
        _report(
            "verified",
            "result_verified",
            "surface_receipt",
            verification_scope=acceptance["scope"],
            current_state_verified=False,
            business_effect_verified=False,
            contract_sha256=contract["contract_sha256"],
            receipt_artifact_id=receipt_artifact["artifact_id"],
        )["checks"]
    )
    return {"status": "verified", "code": "result_verified", "checks": checks}


def _computer(run: Any, step: Any, call: Any, output: dict, context: dict, contract: dict) -> dict:
    from app.application.computer_use import ComputerUseService

    service = ComputerUseService()
    owner = service._owner(context)
    acceptance = contract["surface_acceptance"]
    record = service._read(service._path(owner, "effect", acceptance.get("effect_request_id")))
    actual = record.get("result") or {}
    if not record or record.get("state") != "finished":
        return _report("inconclusive", "result_surface_receipt_unavailable", "computer_effect")
    if (
        record.get("binding") != _binding(contract)
        or record.get("fingerprint") != canonical_hash(step.params)
        or (record.get("run_id"), record.get("step_id")) != (run.run_id, step.step_id)
        or actual.get("request_id") != acceptance.get("effect_request_id")
        or output.get("request_id") != actual.get("request_id")
        or actual.get("success") is not True
        or actual.get("steps_completed") != len(step.params.get("steps") or [])
    ):
        return _report("failed", "result_surface_binding_mismatch", "computer_effect")
    expected, observed = acceptance.get("assertion"), actual.get("verification") or {}
    matched = False
    if acceptance["scope"] == "recorded_visual_pixels" and isinstance(expected, dict):
        pixels, values = expected.get("pixels"), observed.get("actual_pixels")
        matched = bool(
            isinstance(pixels, list)
            and pixels
            and isinstance(values, list)
            and len(values) == len(pixels)
            and type(observed.get("observed_at")) in {int, float}
            and acceptance["frozen_at"] <= observed["observed_at"] <= time.time() + 5
            and all(
                isinstance(value, list)
                and len(value) == 3
                and all(
                    type(channel) is int
                    and 0 <= channel <= 255
                    and abs(channel - wanted) <= pixel.get("tolerance", 0)
                    for channel, wanted in zip(value, pixel["rgb"])
                )
                for pixel, value in zip(pixels, values)
            )
        )
    elif isinstance(expected, dict):
        matched = _assertion_matches(expected, observed, acceptance["frozen_at"])
    if not matched:
        return _report("inconclusive", "result_surface_assertion_unavailable", "computer_effect")
    return _report(
        "verified",
        "result_verified",
        "computer_effect",
        verification_scope=acceptance["scope"],
        request_id=acceptance["effect_request_id"],
        params_sha256=record["fingerprint"],
        contract_sha256=contract["contract_sha256"],
        current_state_verified=False,
        business_effect_verified=False,
    )


def verify_surface_result(run: Any, step: Any, call: Any, output: dict, context: dict) -> dict:
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    if actor_tool_denial(step.tool_id, step.action, context, step.params):
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
    contract = call.metadata.get("verification_contract") or {}
    acceptance = contract.get("surface_acceptance")
    if not isinstance(acceptance, dict) or acceptance.get("scope") in {None, "unavailable"}:
        return _report("inconclusive", "result_surface_contract_unavailable", "surface_contract")
    if step.tool_id == "browser":
        return _browser(run, step, call, output, context, contract)
    if step.tool_id.startswith("mcp__"):
        return _mcp_browser(run, step, call, output, context, contract)
    if step.tool_id == "aiopen":
        return _aiopen(run, step, call, output, context, contract)
    return _computer(run, step, call, output, context, contract)


def _aiopen(run: Any, step: Any, call: Any, output: dict, context: dict, contract: dict) -> dict:
    from app.application.aiopen.agent_bridge import read_aiopen_postcondition

    assertion = contract["surface_acceptance"]["assertion"]
    observed = read_aiopen_postcondition(copy.deepcopy(assertion), context)
    if (
        not _screen_checks_match(observed, assertion, passed=True)
        or output.get("session_id") != assertion["session_id"]
        or observed["request_id"] == output.get("request_id")
        or type(observed.get("observed_at")) not in {int, float}
        or not contract["surface_acceptance"]["frozen_at"]
        <= observed["observed_at"]
        <= time.time() + 5
    ):
        return _report("inconclusive", "result_surface_postcondition_unmet", "owned_screen")
    return _report(
        "verified",
        "result_verified",
        "owned_screen",
        verification_scope="visible_dom_assertions",
        current_state_verified=True,
        business_effect_verified=False,
        session_id=assertion["session_id"],
        request_id=observed["request_id"],
        observed_at=observed["observed_at"],
        assertion_sha256=evidence_hash(assertion),
        observations_sha256=evidence_hash(observed["checks"]),
        contract_sha256=contract["contract_sha256"],
    )


def _screen_checks_match(observed: dict, assertion: dict, *, passed: bool) -> bool:
    expected = ["元素存在"] if assertion.get("ref") or assertion.get("selector") else []
    expected += [
        label
        for field, label in (("value", "控件值"), ("text", "页面文本"), ("url_contains", "URL"))
        if field in assertion and (field == "value" or assertion[field])
    ]
    checks = observed.get("checks")
    return bool(
        observed.get("success") is passed
        and observed.get("session_id") == assertion["session_id"]
        and observed.get("request_id")
        and isinstance(checks, list)
        and expected
        and all(isinstance(item, dict) and type(item.get("ok")) is bool for item in checks)
        and [item.get("check") for item in checks] == expected
        and all(item["ok"] for item in checks) is passed
    )


def _mcp_browser(
    run: Any, step: Any, call: Any, output: dict, context: dict, contract: dict
) -> dict:
    from app.application.agent_orchestrator.browser_tool_process import read_browser_snapshot
    from app.application.tools.mcp.registry import browser_server_config, mcp_session_scope
    from app.domain.autonomy.browser_evidence import snapshot_text, snapshot_url

    acceptance = contract["surface_acceptance"]
    config = browser_server_config(step.tool_id)
    generation = output.get("session_id")
    if (
        config is None
        or canonical_hash(asdict(config)) != acceptance.get("config_sha256")
        or mcp_session_scope(context) != acceptance.get("session_scope")
        or not isinstance(generation, str)
        or not generation
    ):
        return _report("inconclusive", "result_surface_session_unavailable", "browser_session")
    observed = read_browser_snapshot(run, step, call, context, config)
    snapshot = snapshot_text(observed)
    if (
        observed.get("success") is not True
        or observed.get("session_id") != generation
        or not snapshot
        or type(observed.get("observed_at")) not in {int, float}
        or not acceptance["frozen_at"] <= observed["observed_at"] <= time.time() + 5
    ):
        return _report("inconclusive", "result_surface_readback_unavailable", "browser_session")
    condition = acceptance["assertion"]
    matched = (
        condition["expected"] == snapshot_url(observed)
        if condition["kind"] == "url"
        else condition["expected"] in snapshot
    )
    if not matched:
        return _report("inconclusive", "result_surface_postcondition_unmet", "browser_session")
    return _report(
        "verified",
        "result_verified",
        "browser_session",
        verification_scope="visible_page_assertion",
        current_state_verified=True,
        business_effect_verified=False,
        session_id=generation,
        snapshot_sha256=evidence_hash(snapshot),
        assertion_sha256=evidence_hash(condition),
        observed_at=observed["observed_at"],
        contract_sha256=contract["contract_sha256"],
    )
