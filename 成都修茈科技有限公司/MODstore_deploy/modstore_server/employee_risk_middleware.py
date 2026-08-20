# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""MODstore compatibility facade for the FHD autonomy risk SSOT.

No handler classification or approval policy belongs in this module. Keeping
this import path lets existing employee executors migrate without a second
risk implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path


def assess_risk(manifest: Dict[str, Any], handlers: Iterable[str]) -> Tuple[str, str]:
    ensure_fhd_on_path()
    from app.application.employee_runtime.risk_gate import assess_risk as domain_assess_risk

    return domain_assess_risk(manifest, handlers)


def gate_action_or_block(
    employee_id: str,
    manifest: Dict[str, Any],
    handlers: Iterable[str],
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    ensure_fhd_on_path()
    from app.application.employee_runtime.risk_gate import (
        gate_action_or_block as domain_gate_action_or_block,
    )

    return domain_gate_action_or_block(employee_id, manifest, handlers, input_data)


__all__ = ["assess_risk", "gate_action_or_block"]
