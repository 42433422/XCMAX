# mypy: disable-error-code="valid-type"
"""Runtime-status read model extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.self_maintenance_loop_runner_part13_phase01 import _runtime_status_phase_01
from modstore_server.self_maintenance_loop_runner_part13_phase02 import _runtime_status_phase_02
from modstore_server.self_maintenance_loop_runner_part13_phase03 import _runtime_status_phase_03


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def get_self_maintenance_runtime_status(limit: int = 80) -> _facade().Dict[str, _facade().Any]:
    """Return the runtime-consumed self-maintenance loop state.

    This is the read side for the loop. It intentionally consumes the same
    ledger, memory and gate functions used by the scheduler instead of relying
    on a marker file committed by an employee branch.
    """
    state = {"limit": limit}
    _runtime_status_phase_01(state)
    _runtime_status_phase_02(state)
    return _runtime_status_phase_03(state)
