"""PersonaProfileRepository 接口契约测试 + PersonaRepositoryImpl 行为测试。

验证内容：
- 抽象接口不可实例化
- 接口方法签名与契约一致（参数名、返回类型注解）
- 具体实现 PersonaRepositoryImpl 的 CRUD 行为正确
- 缓存命中/回源/降级逻辑正确
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock

import pytest

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, PersonaIdentity, RapportScore
from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl

# ---------------------------------------------------------------------------
# 接口契约测试
# ---------------------------------------------------------------------------


class TestPersonaProfileRepositoryContract:
    """PersonaProfileRepository 抽象接口契约。"""

    def test_cannot_instantiate_abstract_class(self):
        """抽象类不可直接实例化。"""
        with pytest.raises(TypeError):
            PersonaProfileRepository()  # type: ignore[abstract]

    @pytest.mark.parametrize(
        "method_name",
        ["find_by_user_id", "save", "delete", "append_event", "list_recent_events"],
    )
    def test_abstract_method_exists(self, method_name: str):
        """所有抽象方法必须存在且标记为 @abstractmethod。"""
        assert hasattr(PersonaProfileRepository, method_name)
        attr = getattr(PersonaProfileRepository, method_name)
        assert getattr(attr, "__isabstractmethod__", False), f"{method_name} 必须是 @abstractmethod"

    def test_find_by_user_id_signature(self):
        """find_by_user_id 签名: (user_id: str) -> PersonaProfile | None。"""
        sig = inspect.signature(PersonaProfileRepository.find_by_user_id)
        params = list(sig.parameters.keys())
        assert params == ["self", "user_id"], f"参数列表应为 [self, user_id]，实际: {params}"
        assert sig.parameters["user_id"].annotation in (str, "str")

    def test_save_signature(self):
        """save 签名: (profile: PersonaProfile) -> PersonaProfile。"""
        sig = inspect.signature(PersonaProfileRepository.save)
        params = list(sig.parameters.keys())
        assert params == ["self", "profile"], f"参数列表应为 [self, profile]，实际: {params}"

    def test_delete_signature(self):
        """delete 签名: (user_id: str) -> bool。"""
        sig = inspect.signature(PersonaProfileRepository.delete)
        params = list(sig.parameters.keys())
        assert params == ["self", "user_id"], f"参数列表应为 [self, user_id]，实际: {params}"

    def test_append_event_signature(self):
        """append_event 签名: (user_id, event_type, event_data) -> None。"""
        sig = inspect.signature(PersonaProfileRepository.append_event)
        params = list(sig.parameters.keys())
        assert params == ["self", "user_id", "event_type", "event_data"]
        assert sig.parameters["event_data"].annotation in (dict, "dict")

    def test_list_recent_events_signature(self):
        """list_recent_events 签名: (user_id, limit=20) -> list[dict]。"""
        sig = inspect.signature(PersonaProfileRepository.list_recent_events)
        params = list(sig.parameters.keys())
        assert params == ["self", "user_id", "limit"]
        assert sig.parameters["limit"].default == 20

    def test_persona_repository_impl_is_subclass(self):
        """PersonaRepositoryImpl 必须继承 PersonaProfileRepository。"""
        assert issubclass(PersonaRepositoryImpl, PersonaProfileRepository)


# ---------------------------------------------------------------------------
# PersonaRepositoryImpl 行为测试（mock DB session + redis）
# ---------------------------------------------------------------------------


def _make_profile(user_id: str = "u-001", industry: str = "制造业") -> PersonaProfile:
    """构造测试用 PersonaProfile。"""
    return PersonaProfile.create(user_id=user_id, industry=industry)


def _make_mock_session():
    """构造 mock DB session，支持 get/merge/add/query/commit/close。"""
    session = MagicMock()
    session.get.return_value = None
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    return session


def _make_mock_redis():
    """构造 mock RedisCache，支持 get/set/delete。"""
    redis = MagicMock()
    redis.get.return_value = None
    return redis


class TestPersonaRepositoryImplFind:
    """find_by_user_id 行为测试。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """用户不存在时返回 None。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.find_by_user_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_from_db(self):
        """DB 命中时返回 PersonaProfile，字段映射正确。"""
        row = MagicMock()
        row.user_id = "u-001"
        row.identity_name = "生产管家"
        row.identity_brief = "专业地服务用户"
        row.business_domain = "production"
        row.industry = "制造业"
        row.warmth = 0.6
        row.detail = 0.4
        row.proactivity = 0.7
        row.structure = 0.3
        row.rapport_score = 0.5
        row.interaction_count = 10
        row.emotion_signal_count = 2
        row.business_domain_counts = json.dumps({"production": 5})

        session = _make_mock_session()
        session.get.return_value = row

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.find_by_user_id("u-001")

        assert result is not None
        assert result.user_id == "u-001"
        assert result.identity is not None
        assert result.identity.name == "生产管家"
        assert result.identity.business_domain == "production"
        assert result.axes.warmth == 0.6
        assert result.axes.proactivity == 0.7
        assert result.rapport.score == 0.5
        assert result.rapport.interaction_count == 10
        assert result.business_domain_counts == {"production": 5}

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self):
        """缓存命中时跳过 DB 查询。"""
        cached_dict = _make_profile("u-002", "零售业").to_dict()
        redis = _make_mock_redis()
        redis.get.return_value = cached_dict

        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=redis, session_factory=lambda: session)
        result = await repo.find_by_user_id("u-002")

        assert result is not None
        assert result.user_id == "u-002"
        # DB 不应被调用
        session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_exception_returns_none(self):
        """DB 异常时降级返回 None（不抛异常）。"""
        session = _make_mock_session()
        session.get.side_effect = RuntimeError("DB down")

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.find_by_user_id("u-003")

        assert result is None

    @pytest.mark.asyncio
    async def test_corrupted_cache_falls_back_to_db(self):
        """缓存数据损坏时回源 DB。"""
        redis = _make_mock_redis()
        redis.get.return_value = {"invalid": "data"}  # 缺少必需字段

        row = MagicMock()
        row.user_id = "u-004"
        row.identity_name = "业务管家"
        row.identity_brief = ""
        row.business_domain = "general"
        row.industry = "通用"
        row.warmth = 0.5
        row.detail = 0.5
        row.proactivity = 0.5
        row.structure = 0.5
        row.rapport_score = 0.3
        row.interaction_count = 0
        row.emotion_signal_count = 0
        row.business_domain_counts = None

        session = _make_mock_session()
        session.get.return_value = row

        repo = PersonaRepositoryImpl(redis=redis, session_factory=lambda: session)
        result = await repo.find_by_user_id("u-004")

        assert result is not None
        assert result.user_id == "u-004"


class TestPersonaRepositoryImplSave:
    """save 行为测试。"""

    @pytest.mark.asyncio
    async def test_save_returns_profile(self):
        """save 返回被保存的 profile。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        profile = _make_profile("u-005", "物流业")
        result = await repo.save(profile)
        assert result is profile

    @pytest.mark.asyncio
    async def test_save_writes_to_db(self):
        """save 调用 session.merge + commit。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        profile = _make_profile("u-006", "贸易业")
        await repo.save(profile)

        session.merge.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_writes_to_cache(self):
        """save 同时写入缓存。"""
        redis = _make_mock_redis()
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=redis, session_factory=lambda: session)
        profile = _make_profile("u-007", "服务业")
        await repo.save(profile)

        redis.set.assert_called_once()
        cache_key = redis.set.call_args[0][0]
        assert cache_key == "persona:profile:u-007"

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self):
        """DB 保存失败时不抛异常（缓存已持有最新画像）。"""
        session = _make_mock_session()
        session.merge.side_effect = RuntimeError("DB write failed")

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        # 不应抛异常
        result = await repo.save(_make_profile("u-008", "科技业"))
        assert result.user_id == "u-008"


class TestPersonaRepositoryImplDelete:
    """delete 行为测试。"""

    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        """delete 始终返回 True。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.delete("u-009")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_from_db(self):
        """delete 调用 session.get + session.delete + commit。"""
        row = MagicMock()
        session = _make_mock_session()
        session.get.return_value = row

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        await repo.delete("u-010")

        session.delete.assert_called_once_with(row)
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_when_row_not_found(self):
        """DB 中无记录时 delete 仍返回 True，不调用 delete。"""
        session = _make_mock_session()
        session.get.return_value = None

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.delete("u-011")

        assert result is True
        session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_clears_cache(self):
        """delete 同时清除缓存。"""
        redis = _make_mock_redis()
        session = _make_mock_session()

        repo = PersonaRepositoryImpl(redis=redis, session_factory=lambda: session)
        await repo.delete("u-012")

        redis.delete.assert_called_once_with("persona:profile:u-012")


class TestPersonaRepositoryImplEvents:
    """append_event + list_recent_events 行为测试。"""

    @pytest.mark.asyncio
    async def test_append_event_writes_to_db(self):
        """append_event 调用 session.add + commit。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)

        await repo.append_event("u-013", "chat", {"message": "hello"})

        session.add.assert_called_once()
        session.commit.assert_called_once()
        # 验证 event_data 被 JSON 序列化
        added_obj = session.add.call_args[0][0]
        assert added_obj.user_id == "u-013"
        assert added_obj.event_type == "chat"
        assert json.loads(added_obj.event_data) == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_append_event_db_failure_swallowed(self):
        """append_event DB 失败时不抛异常。"""
        session = _make_mock_session()
        session.add.side_effect = RuntimeError("DB down")

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        # 不应抛异常
        await repo.append_event("u-014", "chat", {"msg": "test"})

    @pytest.mark.asyncio
    async def test_list_recent_events_returns_empty(self):
        """无事件时返回空列表。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)

        result = await repo.list_recent_events("u-015")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_recent_events_returns_events(self):
        """有事件时返回正确结构。"""
        row = MagicMock()
        row.id = 1
        row.user_id = "u-016"
        row.event_type = "chat"
        row.event_data = json.dumps({"msg": "hi"})
        row.trace_id = "trace-001"
        row.created_at = MagicMock()
        row.created_at.isoformat.return_value = "2026-01-01T00:00:00"

        session = _make_mock_session()
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            row
        ]

        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)
        result = await repo.list_recent_events("u-016")

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["user_id"] == "u-016"
        assert result[0]["event_type"] == "chat"
        assert result[0]["event_data"] == {"msg": "hi"}
        assert result[0]["trace_id"] == "trace-001"

    @pytest.mark.asyncio
    async def test_list_recent_events_respects_limit(self):
        """limit 参数传递到查询。"""
        session = _make_mock_session()
        repo = PersonaRepositoryImpl(redis=None, session_factory=lambda: session)

        await repo.list_recent_events("u-017", limit=5)

        # 验证 limit 链式调用
        chain = session.query.return_value.filter.return_value.order_by.return_value
        chain.limit.assert_called_once_with(5)
