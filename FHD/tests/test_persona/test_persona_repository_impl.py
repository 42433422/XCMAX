# FHD/tests/test_persona/test_persona_repository_impl.py
"""PersonaRepositoryImpl 仓储实现测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl


class TestPersonaRepositoryImpl:
    """仓储实现测试（使用 mock Redis + DB）。"""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def mock_db_session(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_redis, mock_db_session):
        return PersonaRepositoryImpl(redis=mock_redis, db_session=mock_db_session)

    @pytest.mark.asyncio
    async def test_find_by_user_id_cache_miss_returns_none(self, repo, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        # DB 也无数据
        mock_db = MagicMock()
        mock_db.scalar_one_or_none = MagicMock(return_value=None)
        repo._db_session.execute = AsyncMock(return_value=mock_db)
        result = await repo.find_by_user_id("user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_sets_redis_cache(self, repo, mock_redis):
        profile = PersonaProfile.create("user-1", "零售业")
        await repo.save(profile)
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_clears_redis(self, repo, mock_redis):
        await repo.delete("user-1")
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_append_event_does_not_raise(self, repo):
        await repo.append_event("user-1", "l1_infer", {"warmth": 0.7})
        # 不抛异常即通过

    @pytest.mark.asyncio
    async def test_list_recent_events_returns_list(self, repo, mock_db_session):
        mock_db = MagicMock()
        mock_db.scalars = MagicMock(return_value=[])
        mock_db_session.execute = AsyncMock(return_value=mock_db)
        events = await repo.list_recent_events("user-1", limit=10)
        assert isinstance(events, list)
