"""User preferences and the owned projection of confirmed candidate records."""

from __future__ import annotations

import logging
from typing import Any

from app.application.user_memory.models import UserMemory
from app.application.user_memory.protocols import (
    JsonObject,
    MemoryAccess,
    PreferenceLookup,
    memory_transaction,
)


def sync_preference_projection(
    memory: UserMemory, previous: JsonObject, updated: JsonObject, now: str
) -> None:
    """Move or remove only the legacy preference owned by this memory record."""
    active_preference = (
        updated.get("status") == "active" and updated.get("memory_type") == "preference"
    )
    previous_key = str(previous.get("key") or "").strip()
    key = str(updated.get("key") or "")
    if previous.get("memory_type") == "preference" and (
        not active_preference or previous_key != key
    ):
        preference = memory.preferences.get(previous_key)
        if (
            isinstance(preference, dict)
            and previous.get("memory_id")
            and preference.get("memory_id") == previous["memory_id"]
        ):
            memory.preferences.pop(previous_key, None)
    if active_preference:
        memory.preferences[key] = {
            "value": updated.get("value"),
            "updated_at": now,
            "count": memory.preferences.get(key, {}).get("count", 0) + 1,
            "source": "memory_v2",
            "memory_id": updated["memory_id"],
        }


class PreferenceMemory:
    def __init__(
        self, access: MemoryAccess, get_preference: PreferenceLookup, logger: logging.Logger
    ) -> None:
        self.access = access
        self.get_preference_callback = get_preference
        self.logger = logger

    @memory_transaction
    def add_preference(self, user_id: str, key: str, value: Any) -> None:
        """添加用户偏好"""
        memory = self.access.get_memory(user_id)
        if memory is None:
            memory = self.access.new_memory(user_id)
        memory.preferences[key] = {
            "value": value,
            "updated_at": self.access.now(),
            "count": memory.preferences.get(key, {}).get("count", 0) + 1,
        }
        self.access.save_memory(user_id, memory)
        self.logger.debug("用户 %s 偏好已更新: %s = %s", user_id, key, value)

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        """获取用户偏好"""
        memory = self.access.get_memory(user_id)
        if memory and key in memory.preferences:
            return memory.preferences[key].get("value", default)
        return default

    def get_all_preferences(self, user_id: str) -> dict[str, Any]:
        """获取用户所有偏好"""
        memory = self.access.get_memory(user_id)
        if memory:
            return {k: v.get("value") for k, v in memory.preferences.items()}
        return {}

    def apply_preference_to_slots(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        """将用户偏好应用到槽位"""
        filled_slots = slots.copy()
        if "unit_name" not in filled_slots or not filled_slots["unit_name"]:
            favorite_customer = self.get_preference_callback(user_id, "favorite_customer")
            if favorite_customer:
                filled_slots["unit_name"] = favorite_customer
        if "template" not in filled_slots:
            default_template = self.get_preference_callback(user_id, "default_template")
            if default_template:
                filled_slots["template"] = default_template
        return filled_slots
