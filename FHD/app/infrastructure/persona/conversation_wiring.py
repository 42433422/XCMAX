"""Compose conversation persona adapters at the infrastructure boundary."""

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _InMemoryPersonaRepository:
    """内存版 persona 仓储：无 DB/Redis 环境下的 fallback。

    画像不持久化，进程内缓存；冷启动时 PersonaService 会创建默认画像。
    L1 规则推断 + prompt 生成仍正常工作，仅 L2/L3 缓存和跨会话画像不保留。
    """

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._events: dict[str, list[dict]] = {}

    async def find_by_user_id(self, user_id: str):
        return self._store.get(user_id)

    async def save(self, profile):
        self._store[profile.user_id] = profile
        return profile

    async def delete(self, user_id: str) -> bool:
        return self._store.pop(user_id, None) is not None

    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        events = self._events.setdefault(user_id, [])
        events.append({"type": event_type, "data": event_data})
        if len(events) > 200:
            del events[:-200]

    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        return self._events.get(user_id, [])[-limit:]


def _build_persona_repository():
    """构造持久化 persona 仓储（Redis 热缓存 + DB 冷存储）。

    PersonaRepositoryImpl 内部已对 Redis/DB 不可用做优雅降级；仅当构造本身失败时
    才回退纯内存仓储，确保对话流人格永不因持久化层缺失而中断。
    """
    try:
        from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl

        return PersonaRepositoryImpl()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Persona 持久化仓储不可用，降级内存仓储: %s", exc)
        return _InMemoryPersonaRepository()


def _create_persona_service():
    """创建 PersonaService 实例（持久化仓储 + L1/L2/L3 三层推断）。

    - 持久化：PersonaRepositoryImpl（Redis-first + DB），画像跨重启存活。
    - L1：RuleInferencer（同步实时）。
    - L2：EmbeddingInferencer；未配置 XCAGI_EMBEDDING_API_KEY 时返回中性值自动待命。
    - L3：LlmInferencer，复用主对话 LLM 客户端（PersonaLlmClient 适配器）。
    """
    from app.domain.shared_services.persona.axes_fuser import AxesFuser
    from app.domain.shared_services.persona.embedding_inferencer import EmbeddingInferencer
    from app.domain.shared_services.persona.identity_resolver import IdentityResolver
    from app.domain.shared_services.persona.llm_inferencer import LlmInferencer
    from app.domain.shared_services.persona.param_mapper import PersonaParamMapper
    from app.domain.shared_services.persona.persona_service import PersonaService
    from app.domain.shared_services.persona.prompt_builder import PersonaPromptBuilder
    from app.domain.shared_services.persona.rapport_calculator import RapportCalculator
    from app.domain.shared_services.persona.rule_inferencer import RuleInferencer
    from app.infrastructure.persona.embedding_client import EmbeddingClient
    from app.infrastructure.persona.llm_client_adapter import PersonaLlmClient

    identity_resolver = IdentityResolver()
    return PersonaService(
        repo=_build_persona_repository(),
        rule_inferencer=RuleInferencer(),
        embedding_inferencer=EmbeddingInferencer(EmbeddingClient()),
        llm_inferencer=LlmInferencer(PersonaLlmClient()),
        axes_fuser=AxesFuser(),
        rapport_calculator=RapportCalculator(),
        identity_resolver=identity_resolver,
        prompt_builder=PersonaPromptBuilder(identity_resolver),
        param_mapper=PersonaParamMapper(),
    )


def wire_conversation_persona():
    from app.domain.shared_services.conversation.manager import set_persona_factory

    set_persona_factory(_create_persona_service)
