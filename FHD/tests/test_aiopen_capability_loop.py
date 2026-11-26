"""A self-check must verify the original read receipt and never run a write/chat."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.aiopen.capability_probe import CapabilityProbe
from app.application.aiopen.runtime import RuntimeState


def _probe(catalog, execute):
    return CapabilityProbe(
        RuntimeState({"remote_control_enabled": True}),
        lambda: catalog,
        execute,
        lambda: SimpleNamespace(sessions_info=lambda: [{"id": "screen"}]),
    )


def test_probe_uses_authorized_read_and_preserves_business_receipt():
    execute = Mock(
        return_value={
            "success": True,
            "execution_state": "completed",
            "run_id": "read-run",
            "task_id": "read-task",
        }
    )
    rows = [
        {"operation_id": "capability.customers.create", "risk": "high", "read_only": False},
        {
            "operation_id": "capability.customers.query",
            "risk": "low",
            "read_only": True,
            "required_params": [],
        },
    ]
    result = _probe({"success": True, "capabilities": rows}, execute).run(
        None, {"request_id": "probe-key"}
    )
    assert result["closed_loop"] is True
    assert result["verification_scope"] == "capability_discovery_read_execution_receipt"
    assert result["steps"][1]["run_id"] == "read-run"
    assert result["steps"][1]["task_id"] == "read-task"
    assert execute.call_args.args[1] == {
        "operation_id": "capability.customers.query",
        "params": {},
        "request_id": "probe-key",
    }
    assert len(result["steps"]) == 2


@pytest.mark.parametrize(
    "receipt",
    [
        {"success": True, "execution_state": "queued", "run_id": "r"},
        {"success": True, "execution_state": "unknown", "run_id": "r"},
        {"success": True, "execution_state": "completed"},
        {"success": False, "execution_state": "completed", "run_id": "r"},
    ],
)
def test_acceptance_or_unknown_is_not_closed_loop(receipt):
    catalog = {
        "success": True,
        "capabilities": [
            {"operation_id": "capability.customers.query", "risk": "low", "read_only": True}
        ],
    }
    assert _probe(catalog, Mock(return_value=receipt)).run(None, {})["closed_loop"] is False


@pytest.mark.parametrize("authorized", [False, True])
def test_requested_write_never_runs_as_self_check(authorized):
    execute = Mock()
    catalog = {
        "success": authorized,
        "capabilities": [
            {"operation_id": "capability.customers.delete", "risk": "high", "read_only": False}
        ],
    }
    result = _probe(catalog, execute).run(None, {"operation_id": "capability.customers.delete"})
    assert result["closed_loop"] is False
    execute.assert_not_called()
