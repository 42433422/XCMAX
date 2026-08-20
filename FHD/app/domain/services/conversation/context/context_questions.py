"""Slot-question and action-description helpers for the context facade."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.domain.services.conversation.context.intent_context import PendingIntent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _RequiredSlotsProvider(Protocol):
    def _get_required_slots(self, intent: str) -> list[str]: ...


class ContextQuestionMixin:
    """Cohesive presentation helpers mixed into the public facade."""

    def _get_missing_slots(
        self: _RequiredSlotsProvider, intent: str, slots: dict[str, Any]
    ) -> list[str]:
        required = self._get_required_slots(intent)
        return [slot for slot in required if not slots.get(slot)]

    def _build_followup_question(
        self,
        intent: str,
        missing_slots: list[str],
        current_slots: dict[str, Any],
    ) -> str:
        del current_slots
        if not missing_slots:
            return "请提供更多信息"
        priority_order = ["unit_name", "model_number", "tin_spec", "quantity_tins"]
        for slot in priority_order:
            if slot in missing_slots:
                return self._get_slot_question(intent, slot)
        return f"请问{missing_slots[0]}是多少？"

    def _get_slot_question(self, intent: str, slot: str) -> str:
        questions = {
            "shipment_generate": {
                "unit_name": "请问要发货给哪个客户呢？",
                "model_number": "编号是多少呢？",
                "tin_spec": "规格是多少呢？",
                "quantity_tins": "这次需要多少桶呢？",
            },
            "product_query": {"keyword": "请问要搜索什么关键词？"},
            "customer_query": {"keyword": "请问要搜索什么关键词？"},
        }
        return questions.get(intent, {}).get(slot, f"请问{slot}是多少呢？")

    def _get_action_description(self, intent: str, slots: dict[str, Any]) -> str:
        descriptions = {
            "shipment_generate": f"正在为 {slots.get('unit_name', '该客户')} 生成发货单",
            "products": f"正在查询 {slots.get('keyword', '该产品')} 的产品信息",
            "customers": "正在查询客户信息",
            "shipments": "正在查询发货记录",
            "print_label": "正在处理标签打印",
            "wechat_send": "正在发送微信消息",
        }
        return descriptions.get(intent, f"正在处理 {intent}")

    def _notify_pending_preserved(self, user_id: str, pending: PendingIntent, action: str) -> None:
        try:
            notifier = self._get_notifier()
            if notifier and pending:
                notifier.notify_pending_preserved(user_id, pending.to_dict(), action)
        except RECOVERABLE_ERRORS as error:
            logger.warning("[CONTEXT_FACADE] Failed to notify preserved: %s", error)

    def _get_notifier(self):
        if not hasattr(self, "_notifier"):
            try:
                from app.contexts.context_notifier import get_context_notifier

                self._notifier = get_context_notifier()
            except ImportError:
                self._notifier = None
        return self._notifier
