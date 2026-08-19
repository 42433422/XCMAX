"""Value objects shared by the conversation context facade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.domain.services.conversation.context.intent_context import PendingIntent


class ProcessingAction(Enum):
    GREETING = "greeting"
    GOODBYE = "goodbye"
    HELP = "help"
    SLOT_FILL = "slot_fill"
    TOOL_CALL = "tool_call"
    AI_RESPONSE = "ai_response"
    NEGATED = "negated"
    DUPLICATE_RESPONSE = "duplicate_response"
    INTENT_SWITCH_QUERY = "intent_switch_query"


@dataclass
class IntentResult:
    primary_intent: str | None
    tool_key: str | None
    slots: dict[str, Any]
    is_greeting: bool = False
    is_goodbye: bool = False
    is_help: bool = False
    is_confirmation: bool = False
    is_negation_intent: bool = False
    is_negated: bool = False
    confidence: float = 0.0
    source: str = "unknown"


@dataclass
class ProcessingResult:
    action: ProcessingAction
    text: str
    data: dict[str, Any]
    pending_intent: PendingIntent | None = None
    is_duplicate: bool = False
    cached_response: str | None = None


@dataclass
class ContextDecision:
    should_continue: bool
    action: ProcessingAction
    reason: str
    merged_slots: dict[str, Any] | None = None
    pending_to_preserve: PendingIntent | None = None
