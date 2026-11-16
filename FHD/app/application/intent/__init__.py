"""语义意图识别：semantic-router + fastembed 的本地实现。"""

from __future__ import annotations

from .route_catalog import INTENT_DESCRIPTIONS, INTENT_UTTERANCES
from .semantic_intent import (
    IntentMatch,
    best_intent,
    classify_intents,
    engine_enabled,
    is_available,
    reset_for_tests,
    threshold,
)

__all__ = [
    "INTENT_DESCRIPTIONS",
    "INTENT_UTTERANCES",
    "IntentMatch",
    "best_intent",
    "classify_intents",
    "engine_enabled",
    "is_available",
    "reset_for_tests",
    "threshold",
]
