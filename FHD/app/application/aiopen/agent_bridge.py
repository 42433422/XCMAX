"""Reach the live screen-owning HTTP process from the existing isolated Agent worker."""

from __future__ import annotations

import copy
import ipaddress
import os
import time
from contextlib import suppress
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

from app.application.tools.surface_authority import require_surface_authority
from app.domain.aiopen.principal import ScreenPrincipal
from app.utils.operational_errors import RECOVERABLE_ERRORS

_READS = frozenset({"ui_sessions", "ui_snapshot", "ui_wait", "ui_verify", "ui_screenshot"})


def supports_aiopen_step(action: str) -> bool:
    from app.application.aiopen.definitions import _UI_ACTIONS

    return action == "ui_sessions" or action in _UI_ACTIONS


def screen_verification_schema() -> dict:
    """The existing read-only screen contract, embedded in an approved action."""
    from app.application.aiopen.definitions import TOOL_DEFINITIONS

    schema = copy.deepcopy(
        dict(next(row["inputSchema"] for row in TOOL_DEFINITIONS if row["name"] == "ui_verify"))
    )
    schema.update(
        required=["session_id"],
        additionalProperties=False,
        anyOf=[{"required": [key]} for key in ("ref", "selector", "text", "url_contains")],
    )
    for name, prop in schema["properties"].items():
        if name != "value":
            prop.update(minLength=1, pattern=r"[\s\S]*\S[\s\S]*")
    return schema


def inline_verification(params: dict) -> dict:
    condition = params.get("verification")
    if (
        not isinstance(condition, dict)
        or not Draft202012Validator(screen_verification_schema()).is_valid(condition)
        or condition.get("session_id") != params.get("session_id")
    ):
        return {}
    return copy.deepcopy(condition)


def _host_url() -> str:
    # This is operator configuration, never a model-controlled URL. Refuse redirects.
    base = os.environ.get("XCAGI_AIOPEN_INTERNAL_URL") or "http://127.0.0.1:5000"
    url = urlsplit(base)
    if (
        url.scheme != "http"
        or not url.hostname
        or not ipaddress.ip_address(url.hostname).is_loopback
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("AIOPEN Agent bridge requires the local screen-owning host")
    return base.rstrip("/") + "/api/aiopen/invoke"


def downstream_verification(run, params: dict, context: dict) -> dict:
    from app.application.workflow.workflow_types import plan_from_dict, step_plan_nodes

    session = params.get("session_id")
    if not isinstance(session, str) or not session.strip():
        return {}
    plan = plan_from_dict(run.metadata.get("plan"))
    ordered, error = step_plan_nodes(plan) if plan else ([], "missing plan")
    # Conditional routing may skip a reachable verification. Only the existing
    # unconditional DAG/next semantics are supported for guarded screen writes.
    if error or any(node.branches for node in ordered):
        return {}
    current = next((step for step in run.steps if step.step_id == context["step_id"]), None)
    if current is None:
        return {}
    # Dynamic Xiaox actions have one original business node. The condition is
    # part of that node's exact approved parameters, never a mutable run flag.
    node = next((item for item in ordered if item.node_id == current.node_id), None)
    if (
        node is not None
        and (node.tool_id, node.action, node.params, node.depends_on)
        == (current.tool_id, current.action, current.params, current.depends_on)
        and current.params == params
        and (condition := inline_verification(params))
    ):
        return {"node_id": current.node_id, "params": condition}
    reachable = {current.node_id}
    for node in ordered:
        if node.node_id not in reachable and not reachable.intersection(node.depends_on):
            continue
        reachable.add(node.node_id)
        if node.next:
            reachable.add(node.next)
        if (node.tool_id, node.action, node.params.get("session_id")) != (
            "aiopen",
            "ui_verify",
            session,
        ):
            continue
        # A plan-only or already skipped/completed verification cannot close this action.
        if any(
            (step.node_id, step.tool_id, step.action, step.params, step.depends_on)
            == (node.node_id, node.tool_id, node.action, node.params, node.depends_on)
            and step.status in {"pending", "running", "retrying"}
            for step in run.steps
        ):
            return {"node_id": node.node_id, "params": copy.deepcopy(node.params)}
    return {}


def _has_downstream_verification(run, params: dict, context: dict) -> bool:
    return bool(downstream_verification(run, params, context))


def _request_screen(action: str, params: dict, principal: ScreenPrincipal, timeout: float) -> dict:
    from app.application.aiopen import service

    url = _host_url()
    entry = service.generate_api_key(
        "Agent screen step",
        principal=principal,
        scopes=[action],
        expires_at=time.time() + timeout + 5,
        daily_quota=1,
    )
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                url, json={"tool": action, "args": params}, headers={"X-AIOPEN-Key": entry["key"]}
            )
        result = response.json()
        if (
            not isinstance(result, dict)
            or type(result.get("success")) is not bool
            or response.status_code >= 300
        ):
            raise ValueError("AIOPEN HTTP delivery was not confirmed")
        return result
    finally:
        with suppress(OSError):
            service.revoke_api_key(entry["key"])


def read_aiopen_postcondition(params: dict, context: dict) -> dict:
    """Use the same authenticated screen endpoint, restricted to its read-only verifier."""
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.tool_execution_deadline import remaining_invocation_seconds
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    actor = _bound_actor(context)
    principal = ScreenPrincipal.from_ids(actor.id, context.get("tenant_id"))
    if (
        principal is None
        or not params.get("session_id")
        or actor_tool_denial("aiopen", "ui_verify", context, params)
    ):
        raise PermissionError("screen readback is not authorized")
    timeout = remaining_invocation_seconds(12)
    if timeout <= 0:
        raise TimeoutError("screen readback deadline expired")
    return {**_request_screen("ui_verify", params, principal, timeout), "observed_at": time.time()}


def execute_aiopen_step(action: str, params: dict, context: dict) -> dict:
    from app.application.aiopen.definitions import _UI_ACTION_TIMEOUTS, _UI_ACTIONS
    from app.application.tool_execution_deadline import remaining_invocation_seconds

    if not supports_aiopen_step(action):
        return {"success": False, "error_code": "aiopen_agent_action_unsupported"}
    try:
        actor, run = require_surface_authority(
            "aiopen", action, params, context, approval_required=action not in _READS
        )
        if action not in _READS and not _has_downstream_verification(run, params, context):
            return {
                "success": False,
                "error_code": "aiopen_agent_verification_required",
                "execution_status": "not_started",
                "retryable": False,
                "message": "屏幕写入必须冻结同会话 verification，或在原任务安排同会话后续 ui_verify。",
            }
        principal = ScreenPrincipal.from_ids(actor.id, context.get("tenant_id"))
        if principal is None:
            raise PermissionError("missing screen principal")
        _host_url()
        timeout = remaining_invocation_seconds(
            float(_UI_ACTION_TIMEOUTS.get(_UI_ACTIONS.get(action, ""), 10)) + 2
        )
        if timeout <= 0:
            raise TimeoutError("screen invocation expired")
        # Account-scoped, exact-action, expiring keys use the existing shared key registry.
        # Environment/service keys cannot grant a screen identity.
    except (ValueError, PermissionError, TimeoutError):
        return {
            "success": False,
            "error_code": "aiopen_agent_not_authorized",
            "execution_status": "not_started",
            "retryable": False,
            "message": "屏幕操作未绑定当前任务、账号或审批，未执行。",
        }
    try:
        # This field belongs to the host's independent readback, not the page
        # action protocol. The original parameters remain frozen in its receipt.
        wire_params = {key: value for key, value in params.items() if key != "verification"}
        result = _request_screen(action, wire_params, principal, timeout)
        if action not in _READS and not result["success"]:
            # A DOM action can fail after dispatching an input/click event. A
            # negative acknowledgement alone does not prove no effect occurred.
            result.update(outcome="unknown", retryable=False, reconciliation_required=True)
        # A child trace cannot replace the original durable task identity.
        result.pop("agent_run_id", None)
        result.pop("run_id", None)
        return {
            **result,
            "run_id": run.run_id,
            "action_completed": result["success"],
            "verified": action == "ui_verify" and result["success"],
        }
    except RECOVERABLE_ERRORS:
        return {
            "success": False,
            "error_code": "aiopen_agent_receipt_unknown",
            "run_id": run.run_id,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "message": "屏幕操作回执未确认，必须先回读原页面，不可重复提交。",
        }
