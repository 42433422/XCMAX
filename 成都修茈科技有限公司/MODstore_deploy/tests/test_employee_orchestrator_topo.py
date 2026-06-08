"""Topology-layer tests for employee_orchestrator (no DB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from modstore_server.employee_orchestrator import _topo_layers


@dataclass
class _SubTaskStub:
    employee_id: str
    task_brief: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    priority: int = 100


def test_topo_layers_orders_dependencies_then_priority():
    a = _SubTaskStub(employee_id="a", priority=10)
    b = _SubTaskStub(employee_id="b", priority=20)
    c = _SubTaskStub(employee_id="c", depends_on=["a", "b"], priority=5)
    layers = _topo_layers([c, b, a])

    assert [s.employee_id for s in layers[0]] == ["a", "b"]
    assert [s.employee_id for s in layers[1]] == ["c"]


def test_topo_layers_handles_cycles_by_putting_remaining_last():
    a = _SubTaskStub(employee_id="a", depends_on=["b"])
    b = _SubTaskStub(employee_id="b", depends_on=["a"])
    layers = _topo_layers([a, b])

    flattened = [s.employee_id for layer in layers for s in layer]
    assert sorted(flattened) == ["a", "b"]


def test_plan_and_dispatch_no_user(monkeypatch):
    from modstore_server import employee_orchestrator as eo

    monkeypatch.setattr(eo, "_resolve_uid", lambda _uid: 0)
    out = eo.plan_and_dispatch("brief", {"k": "v"}, created_by_user_id=0)
    assert out == {"ok": False, "error": "no user in DB for duty graph"}
