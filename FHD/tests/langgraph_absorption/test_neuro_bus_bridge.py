# mypy: disable-error-code="arg-type"
"""LG-W1-T5 — NeuroBusEventBridge 事件桥验收。

校验 ``app/infrastructure/workflow/neuro_bus_bridge.py``：
- import / 端口兼容（``EventBusPort`` + ``StateEventPublisher``，均 runtime_checkable）
- recording bus smoke：``state.update`` 事件类型、payload 字段（plan_id/node_id/status/
  output_summary/runtime）、fail-soft
- ``app/neuro_bus/bus.py`` 字节不变（SHA256 锚点），legacy 46 用例由
  ``test_legacy_runtime_contract.py`` 单独回归
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.application.workflow.ports.events import (
    EventBusPort,
    StateEventPublisher,
    StateUpdateEvent,
    StateUpdatePayload,
)
from app.infrastructure.workflow.neuro_bus_bridge import NeuroBusEventBridge
from app.neuro_bus.events.base import NeuroEvent

_BUS_PATH = Path(__file__).resolve().parents[2] / "app" / "neuro_bus" / "bus.py"
_BUS_SHA256 = "337b090051859291a062685c97a2e9f4e4abdaabf58b7743f390abc2bd85ebfe"


class RecordingBus:
    """最小 recording bus：模拟 ``NeuroBus`` 的 ``is_running`` / ``publish`` 契约。"""

    def __init__(self, *, running: bool = True, reject: bool = False):
        self.is_running = running
        self._reject = reject
        self.published: list[NeuroEvent] = []

    def publish(self, event: NeuroEvent) -> bool:
        if self._reject:
            return False
        self.published.append(event)
        return True


def _make_bridge(
    *, running: bool = True, reject: bool = False
) -> tuple[NeuroBusEventBridge, RecordingBus]:
    bus = RecordingBus(running=running, reject=reject)
    return NeuroBusEventBridge(bus=bus), bus


# -- import / 端口兼容 ------------------------------------------------------- #
def test_import_and_satisfies_ports():
    from app.infrastructure.workflow.neuro_bus_bridge import NeuroBusEventBridge as B

    assert B is not None
    bridge, _ = _make_bridge()
    # 两个 application 端口均为 @runtime_checkable，可用 isinstance 静态/运行期校验
    assert isinstance(bridge, EventBusPort)
    assert isinstance(bridge, StateEventPublisher)


# -- recording bus smoke：state.update + payload ----------------------------- #
def test_publish_state_update_records_state_update_event():
    bridge, bus = _make_bridge()
    event = StateUpdateEvent(
        node_id="n1",
        status="succeeded",
        output_summary="done",
        runtime="250ms",
        plan_id="p1",
    )
    bridge.publish_state_update(event)

    assert len(bus.published) == 1
    neuro = bus.published[0]
    assert neuro.event_type == "state.update"
    assert neuro.metadata.domain == "workflow"
    payload = neuro.payload
    assert payload["type"] == "state.update"
    assert payload["plan_id"] == "p1"
    assert payload["node_id"] == "n1"
    assert payload["status"] == "succeeded"
    assert payload["output_summary"] == "done"
    assert payload["runtime"] == "250ms"


def test_publish_state_update_preserves_extra_payload():
    bridge, bus = _make_bridge()
    event = StateUpdateEvent(node_id="n2", plan_id="p9", payload={"extra": 1})
    bridge.publish_state_update(event)
    assert bus.published[0].payload["extra"] == 1
    # 类型化字段优先，不被原始 payload 覆盖
    assert bus.published[0].payload["node_id"] == "n2"


def test_event_bus_port_publish_accepts_raw_dict():
    bridge, bus = _make_bridge()
    raw: StateUpdatePayload = {
        "type": "state.update",
        "plan_id": "p3",
        "node_id": "n3",
        "status": "failed",
    }
    bridge.publish(raw)
    assert len(bus.published) == 1
    assert bus.published[0].event_type == "state.update"
    assert bus.published[0].payload["plan_id"] == "p3"


def test_event_bus_port_publish_plain_dict_sets_type():
    bridge, bus = _make_bridge()
    bridge.publish({"node_id": "n4", "status": "running"})
    assert bus.published[0].payload["type"] == "state.update"


# -- fail-soft --------------------------------------------------------------- #
@pytest.mark.parametrize("exc", [RuntimeError, TypeError, AttributeError])
def test_fail_soft_when_bus_publish_raises(exc):
    bus = RecordingBus()

    def _boom(event: NeuroEvent) -> bool:  # noqa: ARG001
        raise exc("simulated failure")

    bus.publish = _boom  # type: ignore[method-assign]
    bridge = NeuroBusEventBridge(bus=bus)
    # 总线抛任意异常（含不在 RECOVERABLE_ERRORS 内的 TypeError/AttributeError）：
    # 绝不外抛，保证端口「never raise」契约
    bridge.publish_state_update(StateUpdateEvent(node_id="n1"))
    bridge.publish({"node_id": "n2", "status": "running"})
    assert bus.published == []


def test_fail_soft_when_bus_publish_returns_false():
    bridge, bus = _make_bridge(reject=True)
    # bus.publish 返回 False（拒绝/丢件）：仅记录日志，不抛异常
    bridge.publish_state_update(StateUpdateEvent(node_id="n1"))
    bridge.publish({"node_id": "n2", "status": "running"})
    assert bus.published == []


def test_fail_soft_when_bus_not_running():
    bridge, bus = _make_bridge(running=False)
    bridge.publish_state_update(StateUpdateEvent(node_id="n1"))
    assert bus.published == []


# -- bus.py 字节锚点 --------------------------------------------------------- #
def test_bus_py_sha256_unchanged():
    digest = hashlib.sha256(_BUS_PATH.read_bytes()).hexdigest()
    assert digest == _BUS_SHA256
