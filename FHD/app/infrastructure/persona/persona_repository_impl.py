# FHD/app/infrastructure/persona/persona_repository_impl.py
"""Persona 画像仓储实现（Redis 热数据 + DB 冷数据）。"""
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


class PersonaRepositoryImpl(PersonaProfileRepository):
    """Persona 画像仓储实现。

    策略：Redis 优先（热数据，TTL 1h），DB 回源（冷数据）。
    """

    def __init__(self, redis: Any, db_session: Any):
        self._redis = redis
        self._db_session = db_session

    async def find_by_user_id(self, user_id: str) -> PersonaProfile | None:
        """查找画像：Redis 优先，DB 回源。"""
        # 1. Redis 查询
        cache_key = f"{_CACHE_KEY_PREFIX}{user_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            try:
                return PersonaProfile.from_dict(json.loads(cached))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Redis 画像解析失败: %s", e)

        # 2. DB 回源
        result = await self._db_session.execute(
            f"SELECT * FROM {PersonaProfileModel.__tablename__} WHERE user_id = :uid",
            {"uid": user_id},
        )
        row = result.scalar_one_or_none() if hasattr(result, "scalar_one_or_none") else None
        if row is None:
            return None

        # 转换并回填 Redis
        profile = self._row_to_profile(row)
        await self._redis.setex(cache_key, _CACHE_TTL_SECONDS, json.dumps(profile.to_dict()))
        return profile

    async def save(self, profile: PersonaProfile) -> PersonaProfile:
        """保存画像：DB 持久化 + Redis 缓存。"""
        # 1. DB upsert
        model = self._profile_to_model(profile)
        await self._db_session.execute(
            f"INSERT OR REPLACE INTO {PersonaProfileModel.__tablename__} "
            f"(user_id, industry, identity_name, identity_brief, business_domain, "
            f"rapport_score, warmth, detail, proactivity, structure, "
            f"interaction_count, business_domain_counts, emotion_signal_count) "
            f"VALUES (:user_id, :industry, :identity_name, :identity_brief, :business_domain, "
            f":rapport_score, :warmth, :detail, :proactivity, :structure, "
            f":interaction_count, :business_domain_counts, :emotion_signal_count)",
            {
                "user_id": model.user_id,
                "industry": model.industry,
                "identity_name": model.identity_name,
                "identity_brief": model.identity_brief,
                "business_domain": model.business_domain,
                "rapport_score": model.rapport_score,
                "warmth": model.warmth,
                "detail": model.detail,
                "proactivity": model.proactivity,
                "structure": model.structure,
                "interaction_count": model.interaction_count,
                "business_domain_counts": model.business_domain_counts,
                "emotion_signal_count": model.emotion_signal_count,
            },
        )
        await self._db_session.commit()

        # 2. Redis 缓存
        cache_key = f"{_CACHE_KEY_PREFIX}{profile.user_id}"
        await self._redis.setex(cache_key, _CACHE_TTL_SECONDS, json.dumps(profile.to_dict()))
        return profile

    async def delete(self, user_id: str) -> bool:
        """删除画像：DB + Redis。"""
        await self._db_session.execute(
            f"DELETE FROM {PersonaProfileModel.__tablename__} WHERE user_id = :uid",
            {"uid": user_id},
        )
        await self._db_session.commit()
        await self._redis.delete(f"{_CACHE_KEY_PREFIX}{user_id}")
        return True

    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        """追加事件日志。"""
        model = PersonaEventLogModel(
            user_id=user_id,
            event_type=event_type,
            event_data=json.dumps(event_data, ensure_ascii=False),
        )
        self._db_session.add(model)
        await self._db_session.commit()

    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出最近的事件日志。"""
        result = await self._db_session.execute(
            f"SELECT * FROM {PersonaEventLogModel.__tablename__} "
            f"WHERE user_id = :uid ORDER BY created_at DESC LIMIT :limit",
            {"uid": user_id, "limit": limit},
        )
        scalars_result = result.scalars() if hasattr(result, "scalars") else []
        rows = (
            scalars_result.all()
            if hasattr(scalars_result, "all")
            else list(scalars_result or [])
        )
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
        domain_counts = {}
        if hasattr(row, "business_domain_counts") and row.business_domain_counts:
            try:
                domain_counts = json.loads(row.business_domain_counts)
            except json.JSONDecodeError:
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
        return PersonaProfileModel(
            user_id=profile.user_id,
            industry=profile.identity.industry,
            identity_name=profile.identity.name,
            identity_brief=profile.identity.brief,
            business_domain=profile.identity.business_domain,
            rapport_score=profile.rapport.score,
            warmth=profile.axes.warmth,
            detail=profile.axes.detail,
            proactivity=profile.axes.proactivity,
            structure=profile.axes.structure,
            interaction_count=profile.rapport.interaction_count,
            business_domain_counts=json.dumps(profile.business_domain_counts, ensure_ascii=False),
            emotion_signal_count=profile.rapport.emotion_signal_count,
        )
