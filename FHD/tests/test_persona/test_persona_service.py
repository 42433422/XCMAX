# FHD/tests/test_persona/test_persona_service.py
"""PersonaService 主服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.persona_service import PersonaService


class TestPersonaService:
    """PersonaService 主服务测试。"""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.find_by_user_id = AsyncMock(return_value=None)
        repo.save = AsyncMock()
        repo.append_event = AsyncMock()
        return repo

    @pytest.fixture
    def service(self, mock_repo):
        return PersonaService(
            repo=mock_repo,
            rule_inferencer=MagicMock(),
            embedding_inferencer=MagicMock(),
            llm_inferencer=MagicMock(),
            axes_fuser=MagicMock(),
            rapport_calculator=MagicMock(),
            identity_resolver=MagicMock(),
            prompt_builder=MagicMock(),
            param_mapper=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_get_persona_cold_start_returns_default(self, service, mock_repo):
        """冷启动：无历史画像时返回默认画像。"""
        mock_repo.find_by_user_id = AsyncMock(return_value=None)
        profile = await service.get_persona("user-1", industry="零售业")
        assert profile is not None
        assert profile.identity.industry == "零售业"
        assert profile.rapport.score == 0.3  # 冷启动默认

    @pytest.mark.asyncio
    async def test_get_persona_existing_returns_stored(self, service, mock_repo):
        """已有画像时返回存储的画像。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)
        profile = await service.get_persona("user-1", industry="零售业")
        assert profile.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_update_persona_on_message_returns_updated_axes(self, service, mock_repo):
        """消息到达时更新 persona。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        # mock L1 推断
        from app.services.persona.rule_inferencer import RuleInferResult

        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(
                axes=PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9),
                confidence=0.5,
                signals=["emoji"],
            )
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes(warmth=0.8))
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.4, interaction_count=1)
        )

        result = await service.update_on_message(
            user_id="user-1",
            message="你好呀😊",
            history=[],
            industry="零售业",
        )
        assert result is not None
        assert result.axes.warmth == 0.8

    @pytest.mark.asyncio
    async def test_update_persona_saves_to_repo(self, service, mock_repo):
        """更新后保存到仓储。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        from app.services.persona.rule_inferencer import RuleInferResult

        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(axes=PersonaAxes(), confidence=0.0, signals=[])
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes())
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.3, interaction_count=1)
        )

        await service.update_on_message("user-1", "你好", [], "零售业")
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_persona_appends_event(self, service, mock_repo):
        """更新后追加事件日志。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        from app.services.persona.rule_inferencer import RuleInferResult

        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(axes=PersonaAxes(), confidence=0.0, signals=[])
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes())
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.3, interaction_count=1)
        )

        await service.update_on_message("user-1", "你好", [], "零售业")
        mock_repo.append_event.assert_called_once()
