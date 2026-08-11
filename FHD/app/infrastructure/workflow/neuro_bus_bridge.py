"""NeuroBus 事件桥 — 把 workflow application 端口接回 NeuroBus 基础设施事件总线。

LG-W1-T5。本模块是 ``app.neuro_bus.*`` 唯一允许被 import 的 workflow 基础设施落点（§7 门禁豁免B）：
- application 只消费 ``EventBusPort`` / ``StateEventPublisher`` 端口（见
  ``app/application/workflow/ports/events.py``），不直接 import ``app.neuro_bus``。
- 本桥把类型化 ``state.update`` DTO（``StateUpdateEvent``）翻译成 ``NeuroEvent`` 并发布到 NeuroBus，
  payload 携带 ``plan_id`` / ``node_id`` / ``status`` / ``output_summary`` / ``runtime``。
- 全程 fail-soft：总线异常/未启动仅记录日志，绝不抛给调用方，保证不影响 workflow 主流程。

``app/neuro_bus/bus.py`` 保持字节不变，仅被本桥包裹（只读校验）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.workflow.ports.events import StateUpdateEvent, StateUpdatePayload
from app.neuro_bus.bus import NeuroBus, get_neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent

logger = logging.getLogger(__name__)

_STATE_UPDATE_EVENT_TYPE = "state.update"
_STATE_UPDATE_DOMAIN = "workflow"


class NeuroBusEventBridge:
    """把 workflow 状态事件发布到 NeuroBus 的 infrastructure 桥。

    同时满足两个 application 端口（均 ``@runtime_checkable``，可用 ``isinstance`` 校验）：

    - ``StateEventPublisher``：``publish_state_update(StateUpdateEvent)``
    - ``EventBusPort``：``publish(StateUpdateEvent | StateUpdatePayload | dict)``

    默认使用全局 ``get_neuro_bus()`` 实例；测试或组合根可注入独立 bus。
    """

    def __init__(self, bus: NeuroBus | None = None, *, domain: str = _STATE_UPDATE_DOMAIN):
        self._bus = bus if bus is not None else get_neuro_bus()
        self._domain = domain

    # -- StateEventPublisher ------------------------------------------------- #
    def publish_state_update(self, event: StateUpdateEvent) -> None:
        """把类型化 ``state.update`` DTO 发布到 NeuroBus；fail-soft，绝不抛异常。"""
        payload: dict[str, Any] = {
            "type": _STATE_UPDATE_EVENT_TYPE,
            "node_id": event.node_id,
            "status": event.status,
            "output_summary": event.output_summary,
            "runtime": event.runtime,
            "plan_id": event.plan_id,
        }
        if event.payload:
            # 原始 dict 保留（consumer 偏好原形状），但不覆盖类型化字段。
            payload = {**event.payload, **payload}
        self._publish_payload(payload)

    # -- EventBusPort -------------------------------------------------------- #
    def publish(self, event: StateUpdateEvent | StateUpdatePayload | dict[str, Any]) -> None:
        """发布事件；接受类型化事件或原始 state-update dict；fail-soft。"""
        if isinstance(event, StateUpdateEvent):
            self.publish_state_update(event)
            return
        payload = dict(event)
        payload.setdefault("type", _STATE_UPDATE_EVENT_TYPE)
        self._publish_payload(payload)

    # -- 内部实现 ------------------------------------------------------------ #
    def _publish_payload(self, payload: dict[str, Any]) -> None:
        """构建 NeuroEvent 并发布；总线不可用 / 发布失败 / 任何异常一律 log-and-continue。

        端口服约要求 ``publish`` 绝不抛给调用方（见 ``ports/events.py`` docstring），
        故此处按端口契约兜底捕获 ``Exception``：无论总线异常还是编程失误，都只记录日志。
        """
        try:
            if not self._bus.is_running:
                logger.debug(
                    "NeuroBusEventBridge: bus not running; dropping state.update node=%s",
                    payload.get("node_id"),
                )
                return
            neuro_event = NeuroEvent(
                event_type=_STATE_UPDATE_EVENT_TYPE,
                payload=payload,
                priority=EventPriority.NORMAL,
            )
            neuro_event.with_domain(self._domain)
            ok = self._bus.publish(neuro_event)
            if not ok:
                logger.warning(
                    "NeuroBusEventBridge publish rejected/dropped node=%s",
                    payload.get("node_id"),
                )
        except Exception:  # noqa: BLE001 — fail-soft 端口契约：绝不外抛
            logger.exception(
                "NeuroBusEventBridge publish failed node=%s",
                payload.get("node_id"),
            )


__all__ = ["NeuroBusEventBridge"]
