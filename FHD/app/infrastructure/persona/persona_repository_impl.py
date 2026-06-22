# FHD/app/infrastructure/persona/persona_repository_impl.py
"""Persona 画像仓储实现（Redis 热缓存 + 同步 ORM 冷存储）。

设计对齐工程现实（这是它先前"写了却从未被实例化"的根因——原实现假设了
本仓库不存在的 async session + ``redis.setex``）：

- DB 走同步 ``SessionLocal``（本仓库没有 async session）。方法体是同步逻辑，
  仅以 ``async def`` 满足 ``PersonaProfileRepository`` 端口签名（被 ``await`` 调用）。
- 缓存走 ``RedisCache``：Redis 可用时用 Redis，不可用时其内部自动降级进程内本地缓存。
- DB 任何异常（如表尚未建出）都降级为"仅缓存"，保证人格在对话流中始终可用、绝不阻断响应。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)
from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 1 小时
_CACHE_KEY_PREFIX = "persona:profile:"

# 哨兵：区分"未提供 redis（取全局 RedisCache）"与"显式 redis=None（禁用缓存）"
_REDIS_UNSET = object()


class PersonaRepositoryImpl(PersonaProfileRepository):
    """Persona 画像仓储实现（Redis 热缓存优先，同步 DB 回源/落盘）。"""

    def __init__(self, redis: Any = _REDIS_UNSET, session_factory: Any = None):
        if redis is _REDIS_UNSET:
            try:
                from app.utils.redis_cache import get_redis_cache

                redis = get_redis_cache()
            except Exception as exc:  # noqa: BLE001  缓存为可选增强，失败则禁用缓存
                logger.warning("Persona 缓存初始化失败，禁用缓存层: %s", exc)
                redis = None
        if session_factory is None:
            from app.db import SessionLocal

            session_factory = SessionLocal
        self._redis = redis
        self._session_factory = session_factory

    # ---- 缓存辅助（同步，容错；RedisCache 在 Redis 不可用时自动降级本地缓存）----
    def _cache_get(self, user_id: str) -> dict | None:
        if self._redis is None:
            return None
        try:
            return self._redis.get(f"{_CACHE_KEY_PREFIX}{user_id}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Persona 缓存读取失败: %s", exc)
            return None

    def _cache_set(self, profile: PersonaProfile) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(
                f"{_CACHE_KEY_PREFIX}{profile.user_id}",
                profile.to_dict(),
                ttl=_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Persona 缓存写入失败: %s", exc)

    def _cache_del(self, user_id: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(f"{_CACHE_KEY_PREFIX}{user_id}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Persona 缓存删除失败: %s", exc)

    async def find_by_user_id(self, user_id: str) -> PersonaProfile | None:
        """查找画像：缓存优先，DB 回源。"""
        cached = self._cache_get(user_id)
        if cached:
            try:
                return PersonaProfile.from_dict(cached)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Persona 缓存解析失败，回源 DB: %s", exc)

        row = None
        try:
            session = self._session_factory()
            try:
                row = session.get(PersonaProfileModel, user_id)
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001  DB 不可用时降级为空画像（冷启动）
            logger.warning("Persona DB 查询失败，返回空画像（将冷启动）: %s", exc)
            return None

        if row is None:
            return None
        profile = self._row_to_profile(row)
        self._cache_set(profile)
        return profile

    async def save(self, profile: PersonaProfile) -> PersonaProfile:
        """保存画像：先写缓存（即便 DB 挂了也保最新），再落 DB。"""
        self._cache_set(profile)
        try:
            session = self._session_factory()
            try:
                session.merge(self._profile_to_model(profile))
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001  DB 失败不阻断对话（缓存已持有最新画像）
            logger.warning("Persona DB 保存失败（已写缓存，画像仍可用）: %s", exc)
        return profile

    async def delete(self, user_id: str) -> bool:
        """删除画像：缓存 + DB。"""
        self._cache_del(user_id)
        try:
            session = self._session_factory()
            try:
                row = session.get(PersonaProfileModel, user_id)
                if row is not None:
                    session.delete(row)
                    session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Persona DB 删除失败: %s", exc)
        return True

    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        """追加事件日志（审计 + L3 复盘素材）。"""
        try:
            session = self._session_factory()
            try:
                session.add(
                    PersonaEventLogModel(
                        user_id=user_id,
                        event_type=event_type,
                        event_data=json.dumps(event_data, ensure_ascii=False),
                    )
                )
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001  事件日志为辅助数据，失败可忽略
            logger.debug("Persona 事件日志写入失败（忽略）: %s", exc)

    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出最近的事件日志。"""
        rows: list[Any] = []
        try:
            session = self._session_factory()
            try:
                rows = (
                    session.query(PersonaEventLogModel)
                    .filter(PersonaEventLogModel.user_id == user_id)
                    .order_by(PersonaEventLogModel.created_at.desc())
                    .limit(limit)
                    .all()
                )
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Persona 事件日志读取失败: %s", exc)
            return []
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "event_type": row.event_type,
                "event_data": json.loads(row.event_data) if row.event_data else {},
                "trace_id": row.trace_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def _row_to_profile(self, row: Any) -> PersonaProfile:
        """DB 行 → 领域对象。"""
        domain_counts: dict[str, int] = {}
        if getattr(row, "business_domain_counts", None):
            try:
                domain_counts = json.loads(row.business_domain_counts)
            except (json.JSONDecodeError, TypeError):
                pass
        return PersonaProfile(
            user_id=row.user_id,
            identity=PersonaIdentity(
                name=row.identity_name,
                brief=row.identity_brief,
                business_domain=row.business_domain,
                industry=row.industry,
            ),
            axes=PersonaAxes(
                warmth=row.warmth,
                detail=row.detail,
                proactivity=row.proactivity,
                structure=row.structure,
            ),
            rapport=RapportScore(
                score=row.rapport_score,
                interaction_count=row.interaction_count,
                emotion_signal_count=row.emotion_signal_count,
            ),
            business_domain_counts=domain_counts,
        )

    def _profile_to_model(self, profile: PersonaProfile) -> PersonaProfileModel:
        """领域对象 → DB 模型。"""
        identity = profile.identity
        if identity is None:
            raise ValueError("PersonaProfile.identity 不能为空（持久化前必须先解析身份）")
        return PersonaProfileModel(
            user_id=profile.user_id,
            industry=identity.industry,
            identity_name=identity.name,
            identity_brief=identity.brief,
            business_domain=identity.business_domain,
            rapport_score=profile.rapport.score,
            warmth=profile.axes.warmth,
            detail=profile.axes.detail,
            proactivity=profile.axes.proactivity,
            structure=profile.axes.structure,
            interaction_count=profile.rapport.interaction_count,
            business_domain_counts=json.dumps(profile.business_domain_counts, ensure_ascii=False),
            emotion_signal_count=profile.rapport.emotion_signal_count,
        )
