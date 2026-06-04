"""已废弃。"""
import warnings

from app.infrastructure.gateways.ai_conversation import AIConversationService

warnings.warn("ai_conversation_facade 已废弃", DeprecationWarning, stacklevel=2)
__all__ = ["AIConversationService"]
