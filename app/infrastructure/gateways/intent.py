"""意图识别网关。"""

from __future__ import annotations

from typing import Any


def recognize_intents(message: str) -> dict[str, Any]:
    from app.services.intent_service import recognize_intents as _f

    return _f(message)


def get_bert_intent_classifier() -> Any:
    from app.services.bert_intent_service import BertIntentClassifier

    return BertIntentClassifier


__all__ = ["recognize_intents", "get_bert_intent_classifier", "BertIntentClassifier"]

# 兼容 facade 直接 import 类名
from app.services.bert_intent_service import BertIntentClassifier  # noqa: E402
