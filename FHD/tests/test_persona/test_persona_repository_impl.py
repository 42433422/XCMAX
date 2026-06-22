# FHD/tests/test_persona/test_persona_repository_impl.py
"""PersonaRepositoryImpl 真实持久化测试（sqlite :memory: roundtrip）。

替代原先的 mock 断言：现在直接对真实 ORM + sqlite 内存库做 save→find→update→delete
往返，证明画像确实落盘并能读回（cross-restart 持久化的核心保证）。
redis=None 时仅走 DB，结果确定性。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel
from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl


@pytest.fixture
def session_factory():
    # StaticPool + 单连接：让所有 session 共享同一块内存库
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[PersonaProfileModel.__table__, PersonaEventLogModel.__table__],
    )
    return sessionmaker(bind=engine)


@pytest.fixture
def repo(session_factory):
    return PersonaRepositoryImpl(redis=None, session_factory=session_factory)


class TestPersonaRepositoryRoundtrip:
    @pytest.mark.asyncio
    async def test_save_then_find_roundtrip(self, repo):
        profile = PersonaProfile.create("user-1", "零售业")
        await repo.save(profile)

        loaded = await repo.find_by_user_id("user-1")
        assert loaded is not None
        assert loaded.user_id == "user-1"
        assert loaded.identity.name == "门店管家"
        assert loaded.identity.business_domain == "retail"
        assert abs(loaded.axes.warmth - profile.axes.warmth) < 1e-6
        assert loaded.rapport.score == profile.rapport.score

    @pytest.mark.asyncio
    async def test_find_missing_returns_none(self, repo):
        assert await repo.find_by_user_id("nope") is None

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, repo):
        p = PersonaProfile.create("user-2", "物流业")
        await repo.save(p)

        p2 = p.update_axes(PersonaAxes(warmth=0.9, detail=0.2, proactivity=0.8, structure=0.1))
        p2 = p2.update_rapport(RapportScore(score=0.55, interaction_count=42))
        await repo.save(p2)

        loaded = await repo.find_by_user_id("user-2")
        assert loaded is not None
        assert abs(loaded.axes.warmth - 0.9) < 1e-6
        assert loaded.rapport.interaction_count == 42
        assert abs(loaded.rapport.score - 0.55) < 1e-6

    @pytest.mark.asyncio
    async def test_delete_removes_row(self, repo):
        p = PersonaProfile.create("user-3", "零售业")
        await repo.save(p)
        assert await repo.delete("user-3") is True
        assert await repo.find_by_user_id("user-3") is None

    @pytest.mark.asyncio
    async def test_append_and_list_events(self, repo):
        await repo.append_event("user-4", "l1_infer", {"warmth": 0.7})
        events = await repo.list_recent_events("user-4", limit=10)
        assert isinstance(events, list)
        assert len(events) == 1
        assert events[0]["event_type"] == "l1_infer"
        assert events[0]["event_data"] == {"warmth": 0.7}

    @pytest.mark.asyncio
    async def test_db_failure_degrades_gracefully(self):
        """DB 不可用（session 工厂抛错）时，save/find 不抛异常，返回空画像。"""

        def broken_factory():
            raise RuntimeError("DB down")

        broken_repo = PersonaRepositoryImpl(redis=None, session_factory=broken_factory)
        # save 吞掉 DB 错误（缓存层为 None 时直接静默降级）
        await broken_repo.save(PersonaProfile.create("user-5", "零售业"))
        # find 同样降级为 None，不抛
        assert await broken_repo.find_by_user_id("user-5") is None
