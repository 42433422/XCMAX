"""已废弃。"""
import warnings
from app.infrastructure.gateways.intent import BertIntentClassifier
warnings.warn("intent_facade 已废弃", DeprecationWarning, stacklevel=2)
__all__ = ["BertIntentClassifier"]
