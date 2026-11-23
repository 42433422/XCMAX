"""Operator-bound MCP readback using the existing frozen result contract.

An adapter reads a durable operation receipt through an independently reviewed
read-only action. The producing tool's output is never used as the evidence.
Unknown transport effects stay unsettled even when a business effect is observed.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import CannotDetermineSpecification, Unresolvable
from referencing.jsonschema import DRAFT202012

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SOURCES = {"operation_key", "tenant_id", "owner_user_id", "input_sha256"}
_DEFINITION = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "read_action",
        "operation_key_param",
        "read_arguments",
        "postcondition_schema",
    ],
    "properties": {
        "version": {"const": 1},
        "read_action": {"type": "string", "minLength": 1, "maxLength": 200},
        "operation_key_param": {"type": "string", "minLength": 1, "maxLength": 200},
        "read_arguments": {
            "type": "object",
            "minProperties": 3,
            "maxProperties": 16,
            "additionalProperties": {"enum": sorted(_SOURCES)},
        },
        "postcondition_schema": {"type": "object", "minProperties": 1},
    },
}


def _local_references(schema: Any) -> bool:
    try:
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        pending = [(resource, Registry().resolver_with_root(resource))]
        while pending:
            current, resolver = pending.pop()
            if isinstance(current.contents, dict):
                for key in ("$ref", "$dynamicRef"):
                    if key not in current.contents:
                        continue
                    value = current.contents[key]
                    if not isinstance(value, str) or not value.startswith("#"):
                        return False
                    resolver.lookup(value)
            pending.extend(
                (child, resolver.in_subresource(child)) for child in current.subresources()
            )
    except (CannotDetermineSpecification, Unresolvable, TypeError, ValueError):
        return False
    return True


def registered_contract(config, actions: dict, action: str) -> dict | None:
    """Only local policy plus discovered read-only declarations can enable this."""
    definition = config.verification.get(action)
    if config.browser or not Draft202012Validator(_DEFINITION).is_valid(definition):
        return None
    reader = actions.get(definition["read_action"], {})
    writer = actions.get(action, {})
    sources = set(definition["read_arguments"].values())
    schema = definition["postcondition_schema"]
    if (
        definition["read_action"] == action
        or definition["read_action"] not in config.read_only_tools
        or reader.get("read_only") is not True
        or writer.get("read_only") is not False
        or not {"operation_key", "tenant_id", "owner_user_id"}.issubset(sources)
        or definition["operation_key_param"]
        not in writer.get("input_schema", {}).get("required", [])
        or schema.get("type") != "object"
        or not schema.get("required")
        or len(json.dumps(definition, allow_nan=False).encode()) > 16 * 1024
    ):
        return None
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return None
    if not _local_references(schema):
        return None
    return {
        "definition": copy.deepcopy(definition),
        "config_sha256": canonical_hash(asdict(config)),
        "read_schema_sha256": canonical_hash(reader.get("input_schema") or {}),
        "write_schema_sha256": canonical_hash(writer.get("input_schema") or {}),
    }


def capture_acceptance(step, context: dict) -> dict | None:
    from app.application.tools.mcp.registry import _snapshot

    tools, servers = _snapshot()
    config = servers.get(step.tool_id)
    actions = tools.get(step.tool_id, {}).get("actions", {})
    contract = registered_contract(config, actions, step.action) if config else None
    if contract is None:
        return None
    operation = step.params.get(contract["definition"]["operation_key_param"])
    tenant, owner = str(context.get("tenant_id") or ""), str(context.get("user_id") or "")
    if (
        not isinstance(operation, str)
        or not operation.strip()
        or len(operation) > 256
        or not tenant
        or not owner
    ):
        return None
    identity = {
        "operation_key": operation,
        "tenant_id": tenant,
        "owner_user_id": owner,
        "input_sha256": canonical_hash(step.params),
    }
    definition = contract["definition"]
    arguments = {name: identity[value] for name, value in definition["read_arguments"].items()}
    read_schema = actions[definition["read_action"]].get("input_schema") or {}
    try:
        Draft202012Validator.check_schema(read_schema)
        if not _local_references(read_schema) or not Draft202012Validator(
            read_schema, registry=Registry()
        ).is_valid(arguments):
            return None
    except (SchemaError, Unresolvable, TypeError, ValueError):
        return None
    return {**contract, "identity": identity}


def require_write_acceptance(
    tool_id: str, action: str, params: dict, context: dict, *, selected_contract: dict | None
) -> None:
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.tools.surface_authority import require_surface_authority

    _actor, run = require_surface_authority(
        tool_id, action, params, context, approval_required=True
    )
    step = next(s for s in run.steps if s.step_id == context["step_id"])
    call = next((c for c in reversed(run.tool_calls) if c.step_id == step.step_id), None)
    expected = capture_acceptance(step, context)
    contract = (call.metadata.get("verification_contract") or {}) if call else {}
    frozen = contract.get("mcp_acceptance")
    if (
        expected is None
        or selected_contract != {key: value for key, value in expected.items() if key != "identity"}
        or frozen != expected
        or call is None
        or (call.tool_id, call.action, call.params) != (tool_id, action, params)
        or contract.get("contract_sha256")
        != canonical_hash({k: v for k, v in contract.items() if k != "contract_sha256"})
        or actor_tool_denial(tool_id, expected["definition"]["read_action"], context)
    ):
        raise PermissionError("MCP write has no current frozen independent readback contract")


def can_observe_unknown(run, step, call) -> bool:
    from app.domain.task_lifecycle.results import execution_result_outcome_unknown

    return bool(
        step.tool_id.startswith("mcp__")
        and (call.metadata.get("verification_contract") or {}).get("mcp_acceptance")
        and execution_result_outcome_unknown(call.output)
    )


def verify_readback(run, step, call, context: dict) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.tools.mcp.registry import call_mcp_tool
    from app.domain.task_lifecycle.results import execution_result_outcome_unknown

    source = "mcp_operation_readback"
    acceptance = (call.metadata.get("verification_contract") or {}).get("mcp_acceptance")
    expected = capture_acceptance(step, context)
    if not acceptance or expected != acceptance:
        return _report("inconclusive", "mcp_verification_contract_changed", source)
    definition, identity = acceptance["definition"], acceptance["identity"]
    arguments = {name: identity[value] for name, value in definition["read_arguments"].items()}
    if actor_tool_denial(step.tool_id, definition["read_action"], context, arguments):
        return _report("inconclusive", "mcp_verification_read_permission_denied", source)
    try:
        observed = call_mcp_tool(
            step.tool_id,
            definition["read_action"],
            arguments,
            runtime_context=context,
            expected_config_sha256=acceptance["config_sha256"],
            expected_input_schema_sha256=acceptance["read_schema_sha256"],
        )
        receipt = observed.get("structured_content", observed.get("structuredContent"))
        if (
            observed.get("success") is not True
            or not isinstance(receipt, dict)
            or len(json.dumps(receipt, allow_nan=False).encode()) > 64 * 1024
        ):
            return _report("inconclusive", "mcp_verification_source_unavailable", source)
        if any(receipt.get(key) != value for key, value in identity.items()):
            return _report("failed", "mcp_verification_identity_mismatch", source)
        if receipt.get("operation_state") != "completed":
            # Absence, rejection and a still-running operation never authorize replay.
            return _report("inconclusive", "mcp_operation_unsettled", source)
        validator = Draft202012Validator(definition["postcondition_schema"], registry=Registry())
        if not validator.is_valid(receipt.get("effect")):
            return _report("failed", "mcp_postcondition_mismatch", source)
    except (SchemaError, Unresolvable, *RECOVERABLE_ERRORS):
        return _report("inconclusive", "mcp_verification_source_unavailable", source)
    unknown = execution_result_outcome_unknown(call.output)
    return _report(
        "inconclusive" if unknown else "verified",
        "original_execution_unsettled" if unknown else "result_verified",
        source,
        **identity,
        read_action=definition["read_action"],
        receipt_sha256=canonical_hash(receipt),
        business_effect_verified=True,
        verification_scope="original_operation_effect",
        execution_settled=not unknown,
        fresh_execution=False,
    )
