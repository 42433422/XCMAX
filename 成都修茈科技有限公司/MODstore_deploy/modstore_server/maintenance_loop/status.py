"""Compose the runtime read models without dispatching employee work."""

from __future__ import annotations

from typing import Any, Dict

from . import status_contract, status_evidence, status_governance


def get_self_maintenance_runtime_status(limit: int = 80) -> Dict[str, Any]:
    """Return the runtime-consumed self-maintenance loop state.

    This is the read side for the loop. It intentionally consumes the same
    ledger, memory and gate functions used by the scheduler instead of relying
    on a marker file committed by an employee branch.
    """
    state = {"limit": limit}
    status_evidence.collect_runtime_evidence(state)
    status_governance.project_governance_state(state)
    return status_contract.render_runtime_contract(state)
