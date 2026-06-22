# FHD/tests/test_persona/test_api_integration.py
"""api.py persona 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, PersonaIdentity, RapportScore


class TestApiPersonaIntegration:
    """api.py 与 persona 集成测试。"""

    @pytest.mark.asyncio
    async def test_persona_service_injected_into_conversation_service(self):
        """AIConversationService 可注入 PersonaService。"""
        from app.services.conversation.manager import AIConversationService

        try:
            service = AIConversationService()
        except Exception as exc:  # 外部依赖缺失时跳过
            pytest.skip(f"AIConversationService 初始化需要外部依赖: {exc}")
        # persona_service 默认为 None（未注入时走 fallback）
        assert hasattr(service, "persona_service")
        assert service.persona_service is None

    def test_legacy_base_prompt_constant_exists(self):
        """旧 base_prompt 作为 fallback 常量保留。"""
        from app.services.conversation.api import LEGACY_BASE_PROMPT

        assert "专业的业务助手" in LEGACY_BASE_PROMPT

    @pytest.mark.asyncio
    async def test_build_system_prompt_with_persona(self):
        """注入 persona 时使用 persona prompt。"""
        from app.services.conversation.api import ApiMixin

        # 创建 mock persona service
        mock_persona_service = MagicMock()
        mock_persona_service.update_on_message = AsyncMock(
            return_value=PersonaProfile(
                user_id="user-1",
                identity=PersonaIdentity(
                    name="考勤管家",
                    brief="专业地服务用户",
                    business_domain="attendance",
                    industry="服务业",
                ),
                axes=PersonaAxes(warmth=0.8, detail=0.5, proactivity=0.6, structure=0.7),
                rapport=RapportScore(score=0.5, interaction_count=100),
            )
        )
        mock_persona_service.build_prompt = MagicMock(
            return_value="你是考勤管家，专业地服务用户。\n\n用口语化表达。"
        )

        # 创建 ApiMixin 实例
        class FakeApiMixin(ApiMixin):
            def __init__(self):
                self.persona_service = mock_persona_service
                self._build_context_prompt = MagicMock(return_value="当前意图：查询")

        mixin = FakeApiMixin()

        # 测试 _build_system_prompt 方法
        prompt = mixin._build_system_prompt_with_persona(
            user_id="user-1",
            message="你好",
            history=[],
            industry="服务业",
            context_prompt="当前意图：查询",
        )
        assert "考勤管家" in prompt
