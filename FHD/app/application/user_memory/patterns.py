"""Operation history, pattern retrieval and chronological habit analysis."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.user_memory.analysis import (
    analyze_action_sequence,
    suggestions_for_sequences,
)
from app.domain.user_memory.analysis import (
    chronological_contexts as chronological_contexts,
)
from app.application.user_memory.models import ActionPattern, ContextSummary, UserMemory
from app.application.user_memory.ports import JsonObject, MemoryAccess, memory_transaction


class ActionFactory(Protocol):
    def __call__(
        self,
        *,
        pattern: str,
        intent: str,
        slots: JsonObject,
        frequency: int,
        last_used: str,
        confidence: float,
    ) -> ActionPattern: ...


class ContextFactory(Protocol):
    def __call__(
        self, *, timestamp: str, intent: str, slots: JsonObject, message: str, turn_count: int
    ) -> ContextSummary: ...


@dataclass(frozen=True)
class PatternPorts:
    action_factory: ActionFactory
    context_factory: ContextFactory
    pattern_key: Callable[[str, JsonObject], str]
    save_context: Callable[[UserMemory, str, JsonObject, str], None]
    similarity: Callable[[JsonObject, JsonObject], float]
    analyze_sequence: Callable[[UserMemory], list[JsonObject]]
    max_actions: Callable[[], int]
    max_contexts: Callable[[], int]


class ActionMemory:
    def __init__(self, access: MemoryAccess, ports: PatternPorts, logger: logging.Logger) -> None:
        self.access = access
        self.ports = ports
        self.logger = logger

    @memory_transaction
    def record_action(
        self, user_id: str, intent: str, slots: dict[str, Any], message: str = ""
    ) -> None:
        """记录用户操作模式"""
        memory = self.access.get_memory(user_id)
        if memory is None:
            memory = self.access.new_memory(user_id)
        pattern_key = self.ports.pattern_key(intent, slots)
        existing_pattern = None
        pattern_idx = -1
        for idx, action in enumerate(memory.frequent_actions):
            if action.get("pattern") == pattern_key:
                existing_pattern = action
                pattern_idx = idx
                break
        if existing_pattern:
            existing_pattern["frequency"] += 1
            existing_pattern["last_used"] = self.access.now()
            existing_pattern["confidence"] = min(0.99, existing_pattern["confidence"] + 0.05)
            memory.frequent_actions[pattern_idx] = existing_pattern
        else:
            new_pattern = self.ports.action_factory(
                pattern=pattern_key,
                intent=intent,
                slots=slots,
                frequency=1,
                last_used=self.access.now(),
                confidence=0.5,
            )
            memory.frequent_actions.insert(0, new_pattern.to_dict())
        memory.frequent_actions.sort(key=lambda x: x.get("frequency", 0), reverse=True)
        memory.frequent_actions = memory.frequent_actions[: self.ports.max_actions()]
        self.ports.save_context(memory, intent, slots, message)
        self.access.save_memory(user_id, memory)
        self.logger.debug("用户 %s 操作已记录: intent=%s, slots=%s", user_id, intent, slots)

    def make_pattern_key(self, intent: str, slots: dict[str, Any]) -> str:
        """生成模式唯一键"""
        key_parts = [intent]
        important_slots = ["unit_name", "product_name", "model_number"]
        for slot_key in important_slots:
            if slot_key in slots and slots[slot_key]:
                key_parts.append(f"{slot_key}={slots[slot_key]}")
        key_str = "|".join(key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def save_context_summary(
        self, memory: UserMemory, intent: str, slots: dict[str, Any], message: str
    ) -> None:
        """保存上下文摘要"""
        summary = self.ports.context_factory(
            timestamp=self.access.now(),
            intent=intent,
            slots=slots,
            message=message[:100] if message else "",
            turn_count=1,
        )
        memory.historical_contexts.insert(0, summary.to_dict())
        memory.historical_contexts = memory.historical_contexts[: self.ports.max_contexts()]

    def get_recent_actions(
        self, user_id: str, limit: int = 5, intent_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """获取最近操作模式"""
        memory = self.access.get_memory(user_id)
        if not memory:
            return []
        actions = memory.frequent_actions
        if intent_filter:
            actions = [a for a in actions if a.get("intent") == intent_filter]
        return actions[:limit]

    def get_similar_pattern(
        self, user_id: str, intent: str, slots: dict[str, Any], threshold: float = 0.2
    ) -> dict[str, Any] | None:
        """查找相似的操作模式"""
        memory = self.access.get_memory(user_id)
        if not memory:
            return None
        best_match = None
        best_score = 0.0
        for action in memory.frequent_actions:
            if action.get("intent") != intent:
                continue
            score = self.ports.similarity(slots, action.get("slots", {}))
            action_confidence = action.get("confidence", 0.5)
            if score >= 0.5:
                combined_score = score
            else:
                combined_score = score * action_confidence
            if combined_score > best_score and combined_score >= threshold:
                best_score = combined_score
                best_match = action
        if best_match:
            best_match["match_score"] = round(best_score, 3)
        return best_match

    def calculate_similarity(self, slots1: dict[str, Any], slots2: dict[str, Any]) -> float:
        """计算槽位相似度"""
        if not slots1 and (not slots2):
            return 1.0
        important_keys = ["unit_name", "spec", "model_number", "quantity", "product_name"]
        match_count = 0
        total_count = 0
        for key in important_keys:
            v1 = slots1.get(key, "") or slots1.get(key)
            v2 = slots2.get(key, "") or slots2.get(key)
            if v1 and v2:
                total_count += 1
                if str(v1) == str(v2):
                    match_count += 1
        if total_count == 0:
            return 0.5
        return match_count / total_count

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, Any]]:
        """获取操作习惯建议"""
        memory = self.access.get_memory(user_id)
        if not memory:
            return []
        return suggestions_for_sequences(self.ports.analyze_sequence(memory))

    def analyze_action_sequence(self, memory: UserMemory) -> list[dict[str, Any]]:
        """分析操作序列"""
        return analyze_action_sequence(memory)
