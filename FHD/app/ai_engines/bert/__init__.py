"""
BERT 意图分类服务

此模块已迁移到 app/ai_engines/bert/
"""

from typing import Any

BertIntentClassifier: Any

try:
    from app.ai_engines.bert.intent_service import BertIntentClassifier as _RealBertClassifier

    BertIntentClassifier = _RealBertClassifier
except ModuleNotFoundError as exc:
    if (exc.name or "").split(".", 1)[0] not in {"torch", "transformers"}:
        raise

    class _FallbackBertClassifier:
        def __init__(self, *args, **kwargs):
            self.available = False

        def is_available(self) -> bool:
            return False

        def classify(self, *args, **kwargs):
            return []

        def predict(self, *args, **kwargs):
            return []

    BertIntentClassifier = _FallbackBertClassifier

__all__ = ["BertIntentClassifier"]
