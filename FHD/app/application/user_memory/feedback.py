"""Feedback history, confidence adjustments and error statistics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.domain.user_memory.analysis import feedback_stats
from app.application.user_memory.models import FeedbackRecord, UserMemory
from app.application.user_memory.ports import JsonObject, MemoryAccess, memory_transaction


class FeedbackFactory(Protocol):
    def __call__(
        self,
        *,
        timestamp: str,
        message: str,
        recognized_intent: str,
        user_feedback: str,
        corrected_intent: str | None,
        slots: JsonObject,
    ) -> FeedbackRecord: ...


@dataclass(frozen=True)
class FeedbackPorts:
    record_factory: FeedbackFactory
    adjust_weights: Callable[[UserMemory, str, str | None, str], None]
    max_history: Callable[[], int]
    corrected_policy: Literal["reassign", "legacy_penalty"] = "reassign"


class FeedbackMemory:
    def __init__(self, access: MemoryAccess, ports: FeedbackPorts, logger: logging.Logger) -> None:
        self.access = access
        self.ports = ports
        self.logger = logger

    @memory_transaction
    def add_feedback(
        self,
        user_id: str,
        message: str,
        recognized_intent: str,
        feedback: str,
        corrected_intent: str | None = None,
        slots: dict[str, Any] | None = None,
    ) -> None:
        """添加用户反馈"""
        memory = self.access.get_memory(user_id)
        if memory is None:
            memory = self.access.new_memory(user_id)
        record = self.ports.record_factory(
            timestamp=self.access.now(),
            message=message[:200] if message else "",
            recognized_intent=recognized_intent,
            user_feedback=feedback,
            corrected_intent=corrected_intent,
            slots=slots or {},
        )
        memory.feedback_history.insert(0, record.to_dict())
        memory.feedback_history = memory.feedback_history[: self.ports.max_history()]
        self.ports.adjust_weights(memory, recognized_intent, corrected_intent, feedback)
        self.access.save_memory(user_id, memory)
        self.logger.debug(
            "用户 %s 反馈已记录: feedback=%s, recognized=%s", user_id, feedback, recognized_intent
        )

    def adjust_pattern_weights(
        self,
        memory: UserMemory,
        recognized_intent: str,
        corrected_intent: str | None,
        feedback: str,
    ) -> None:
        """调整模式权重"""
        weight_delta = 0.0
        target_intent = recognized_intent
        if feedback == "confirmed":
            weight_delta = 0.1
        elif feedback == "negated":
            weight_delta = -0.15
        elif feedback == "corrected" and corrected_intent:
            target_intent = corrected_intent
            if self.ports.corrected_policy == "legacy_penalty":
                weight_delta = -0.1
            else:
                for action in memory.frequent_actions:
                    if action.get("intent") == recognized_intent:
                        new_confidence = action.get("confidence", 0.5) - 0.1
                        action["confidence"] = max(0.1, min(0.99, new_confidence))
                weight_delta = 0.1
        for action in memory.frequent_actions:
            if action.get("intent") == target_intent:
                new_confidence = action.get("confidence", 0.5) + weight_delta
                action["confidence"] = max(0.1, min(0.99, new_confidence))

    def get_feedback_stats(self, user_id: str) -> dict[str, Any]:
        """获取反馈统计"""
        return feedback_stats(self.access.get_memory(user_id))
