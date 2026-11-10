"""
AI Conversation Service 测试
"""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.shared_services.ai_conversation_service import AIConversationService


class TestAIConversationService:
    """AI 对话服务测试"""

    @pytest.fixture
    def service(self):
        with patch(
            "app.domain.shared_services.ai_conversation_service.init_ai_conversation_service"
        ):
            return AIConversationService()

    def test_service_init(self, service):
        assert service is not None
        assert not hasattr(service, "_recognize_intent")

    @pytest.mark.asyncio
    async def test_chat_delegates_to_unified_chat_application_service(self, service, monkeypatch):
        mainline = MagicMock()
        mainline.process_chat.return_value = {
            "success": True,
            "response": "平台模型已回复",
            "data": {"action": "model_reply"},
        }
        monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: mainline)

        result = await service.chat("owner", "你好", {"conversation_id": "chat-1"})

        mainline.process_chat.assert_called_once()
        assert result["text"] == "平台模型已回复"
        assert result["action"] == "model_reply"

    def test_handle_negative_intent(self, service):
        from app.domain.shared_services.intent_service import recognize_intents

        result = recognize_intents("不要生成发货单")
        assert result.get("is_negation_intent") or result.get("is_negated")

    def test_handle_greeting(self, service):
        from app.domain.shared_services.intent_service import recognize_intents

        result = recognize_intents("你好")
        assert result.get("is_greeting") is True
