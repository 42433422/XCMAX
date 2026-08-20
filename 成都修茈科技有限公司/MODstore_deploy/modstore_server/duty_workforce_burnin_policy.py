# mypy: disable-error-code="attr-defined, index, no-any-return, operator, union-attr, valid-type"
"""Eligibility policy for duty-workforce burn-in."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from modstore_server.duty_burn_in_handlers import select_reviewed_burn_in_handlers
from modstore_server.duty_workforce_burnin_constants import (
    CAPABILITY_HANDLERS as _CAPABILITY_HANDLERS,
)
from modstore_server.duty_workforce_burnin_constants import (
    DANGEROUS_HANDLERS as _DANGEROUS_HANDLERS,
)
from modstore_server.duty_workforce_burnin_constants import (
    PROHIBITED_SEMANTICS as _PROHIBITED_SEMANTICS,
)
from modstore_server.employee_runtime import parse_employee_config_v2
from modstore_server.operational_errors import BOUNDARY_ERRORS


def _actions_config(manifest: Dict[str, Any]) -> Dict[str, Any]:
    config = parse_employee_config_v2(manifest)
    actions = config.get("actions")
    if not isinstance(actions, dict):
        return {}
    nested_actions = actions.get("actions")
    return dict(nested_actions) if isinstance(nested_actions, dict) else dict(actions)


def _extract_handlers(manifest: Dict[str, Any]) -> list[str]:
    actions = _actions_config(manifest)
    values = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    return [str(item).strip() for item in values if str(item).strip()]


def _contract_semantics(contract: Dict[str, Any]) -> str:
    selected = {
        "employee_id": contract.get("employee_id"),
        "mission": contract.get("mission"),
        "mode": contract.get("mode"),
        "acceptance": contract.get("acceptance"),
        "trigger": contract.get("trigger"),
    }
    return json.dumps(selected, ensure_ascii=False, sort_keys=True).lower()


def _payload_sha256(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prohibited_contract_reason(contract: Dict[str, Any]) -> str:
    text = _contract_semantics(contract)
    for token in _PROHIBITED_SEMANTICS:
        if token.lower() in text:
            return f"prohibited_semantics:{token}"
    return ""


def assess_burn_in_eligibility(
    employee_id: str,
    contract: Dict[str, Any],
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the same fail-closed eligibility gate at plan and execution time."""

    risk = str(contract.get("risk_level") or "").strip().lower()
    low_or_read_only_risk = risk in {"low", "read_only", "readonly"}
    prohibited_reason = _prohibited_contract_reason(
        {
            **contract,
            "employee_id": str(employee_id or contract.get("employee_id") or ""),
        }
    )
    try:
        handlers = _extract_handlers(manifest)
        actions = _actions_config(manifest)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return {
            "eligible": False,
            "reason": f"manifest_invalid:{type(exc).__name__}",
        }
    selection = select_reviewed_burn_in_handlers(
        actions,
        handlers,
        dangerous_handlers=_DANGEROUS_HANDLERS,
        capability_handlers=_CAPABILITY_HANDLERS,
    )
    if selection.get("error"):
        return selection["error"]
    capability_handlers = selection["capability_handlers"]
    burn_in_handlers_explicit = selection["burn_in_handlers_explicit"]
    if "direct_python" in capability_handlers and "agent" not in capability_handlers:
        direct = (
            actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
        )
        input_schema = (
            direct.get("input_schema") if isinstance(direct.get("input_schema"), dict) else {}
        )
        output_schema = (
            direct.get("output_schema") if isinstance(direct.get("output_schema"), dict) else {}
        )
        fixture = (
            direct.get("burn_in_fixture") if isinstance(direct.get("burn_in_fixture"), dict) else {}
        )
        required_input = [
            str(item).strip() for item in input_schema.get("required") or [] if str(item).strip()
        ]
        required_output = {
            str(item).strip() for item in output_schema.get("required") or [] if str(item).strip()
        }
        fixture_complete = bool(required_input) and all(key in fixture for key in required_input)
        required_receipt_fields = {
            "ok",
            "status",
            "summary",
            "evidence",
            "read_only",
            "side_effects",
        }
        if not (
            str(direct.get("implementation") or "").strip().lower() == "employee_module"
            and str(direct.get("execution_mode") or "").strip().lower() == "deterministic"
            and direct.get("read_only") is True
            and fixture_complete
            and required_receipt_fields.issubset(required_output)
        ):
            return {
                "eligible": False,
                "reason": "direct_python_input_not_declared",
                "handlers": handlers,
                "capability_handlers": capability_handlers,
            }
        policy = (
            direct.get("burn_in_policy") if isinstance(direct.get("burn_in_policy"), dict) else {}
        )
        reviewed_fixture_only = all(
            (
                policy.get("reviewed") is True,
                str(policy.get("scope") or "").strip().lower() == "fixture_only",
                policy.get("external_effects") is False,
            )
        )
        semantics_override = (
            reviewed_fixture_only and policy.get("allow_prohibited_semantics_fixture") is True
        )
        if prohibited_reason and not semantics_override:
            return {"eligible": False, "reason": prohibited_reason}
        if risk == "high" and (
            not reviewed_fixture_only or policy.get("allow_high_risk_fixture") is not True
        ):
            return {"eligible": False, "reason": "risk_not_low:high"}
        if risk == "high":
            eligibility_reason = "eligible_high_risk_fixture_only_direct_python"
        elif risk == "medium":
            eligibility_reason = "eligible_medium_read_only_direct_python"
        elif low_or_read_only_risk:
            eligibility_reason = "eligible_read_only_direct_python"
        else:
            return {"eligible": False, "reason": f"risk_not_low:{risk or '?'}"}
        return {
            "eligible": True,
            "reason": eligibility_reason,
            "risk_level": risk,
            "handlers": handlers,
            "capability_handlers": capability_handlers,
            "burn_in_fixture": fixture,
            "burn_in_handlers_explicit": burn_in_handlers_explicit,
            "prohibited_semantics_fixture_override": bool(prohibited_reason and semantics_override),
            "high_risk_fixture_only": risk == "high",
        }
    if prohibited_reason:
        return {"eligible": False, "reason": prohibited_reason}
    if not low_or_read_only_risk:
        return {"eligible": False, "reason": f"risk_not_low:{risk or '?'}"}
    return {
        "eligible": True,
        "reason": "eligible_read_only_agent",
        "risk_level": risk,
        "handlers": handlers,
        "capability_handlers": capability_handlers,
        "burn_in_handlers_explicit": burn_in_handlers_explicit,
    }
