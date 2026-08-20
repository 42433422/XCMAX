"""Configuration-driven slot validation and follow-up prompts."""

from __future__ import annotations

from typing import Any


class SlotValidator:
    REQUIRED_SLOTS = {
        "shipment_generate": {
            "required": ["unit_name", "model_number", "tin_spec", "quantity_tins"],
            "optional": ["contact_phone"],
        },
        "product_query": {"required": [], "optional": ["keyword", "model_number", "tin_spec"]},
        "customer_query": {"required": [], "optional": ["keyword", "customer_name"]},
        "customer_supplement": {"required": ["field_name", "field_value"], "optional": []},
        "print_label": {"required": ["unit_name"], "optional": ["quantity_tins"]},
        "price_list": {"required": ["customer_name"], "optional": ["keyword"]},
        "wechat_send": {"required": ["unit_name"], "optional": ["contact_person"]},
    }
    SLOT_LABELS = {
        "unit_name": "客户",
        "model_number": "编号",
        "tin_spec": "规格",
        "quantity_tins": "桶数",
        "contact_phone": "联系电话",
        "keyword": "关键词",
        "customer_name": "客户名称",
        "field_name": "字段名",
        "field_value": "字段值",
    }

    def validate(self, intent: str, slots: dict[str, Any]) -> tuple[bool, list[str]]:
        if intent not in self.REQUIRED_SLOTS:
            return True, []
        missing = [
            slot for slot in self.REQUIRED_SLOTS[intent].get("required", []) if not slots.get(slot)
        ]
        return len(missing) == 0, missing

    def build_followup(
        self, intent: str, missing_slots: list[str], current_slots: dict[str, Any] | None = None
    ) -> str:
        del current_slots
        if not missing_slots:
            return ""
        for slot in ["unit_name", "model_number", "tin_spec", "quantity_tins"]:
            if slot in missing_slots:
                return self._build_single_question(intent, slot)
        return f"请问{missing_slots[0]}是多少？"

    def _build_single_question(self, intent: str, slot: str) -> str:
        if intent == "shipment_generate":
            questions = {
                "unit_name": "请问要发货给哪个客户呢？",
                "model_number": "编号是多少呢？",
                "tin_spec": "规格是多少呢？",
                "quantity_tins": "这次需要多少桶呢？",
            }
            return questions.get(slot, f"请问{slot}是多少呢？")
        return f"请问{self.SLOT_LABELS.get(slot, slot)}是多少呢？"


__all__ = ["SlotValidator"]
