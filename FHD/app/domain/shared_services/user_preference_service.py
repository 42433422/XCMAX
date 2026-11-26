"""
用户偏好服务模块

提供用户偏好设置的业务逻辑。
"""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import cast

from sqlalchemy import text

from app.db.models import UserPreference
from app.db.session import get_db
from app.di.registry import get_service_registry
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin

logger = logging.getLogger(__name__)


def _lock_preference_write(db, user_id: str, preference_key: str) -> None:
    """Serialize writes even before the first preference row exists."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        # Acquire the database writer reservation before reading the old value.
        db.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        identity = json.dumps([user_id, preference_key], ensure_ascii=False)
        lock_id = int.from_bytes(
            hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big", signed=True
        )
        db.execute(
            text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"), {"lock_id": lock_id}
        )
    else:
        raise ValueError("Unsupported database dialect for atomic preference writes")


class UserPreferenceService(NeuroEventPublisherMixin):
    """用户偏好服务类"""

    def __init__(self):
        """初始化用户偏好服务"""
        pass

    def get_preference(self, user_id: str, preference_key: str) -> str | None:
        """
        获取用户偏好

        Args:
            user_id: 用户 ID
            preference_key: 偏好键

        Returns:
            偏好值，如果不存在则返回 None
        """
        with get_db() as db:
            preference = (
                db.query(UserPreference)
                .filter(
                    UserPreference.user_id == user_id,
                    UserPreference.preference_key == preference_key,
                )
                .first()
            )

            return preference.preference_value if preference else None

    def set_preference(self, user_id: str, preference_key: str, preference_value: str) -> bool:
        """
        设置用户偏好

        Args:
            user_id: 用户 ID
            preference_key: 偏好键
            preference_value: 偏好值

        Returns:
            是否设置成功
        """
        self.mutate_preference(user_id, preference_key, lambda _old: preference_value)
        return True

    def mutate_preference(
        self, user_id: str, preference_key: str, transform: Callable[[str | None], str]
    ) -> str:
        """Read, transform and persist under one database transaction."""
        with get_db() as db:
            _lock_preference_write(db, user_id, preference_key)
            rows = (
                db.query(UserPreference)
                .filter(
                    UserPreference.user_id == user_id,
                    UserPreference.preference_key == preference_key,
                )
                .limit(2)
                .all()
            )
            if len(rows) > 1:
                raise ValueError("Ambiguous duplicate preference rows")
            preference = rows[0] if rows else None
            value = transform(preference.preference_value if preference else None)
            if not isinstance(value, str):
                raise TypeError("Preference value must be a string")
            if preference is not None:
                preference.preference_value = value
            else:
                db.add(
                    UserPreference(
                        user_id=user_id,
                        preference_key=preference_key,
                        preference_value=value,
                    )
                )
            # The existing get_db scope owns commit and rollback.
        return value

    def get_all_preferences(self, user_id: str) -> dict[str, str]:
        """
        获取用户所有偏好

        Args:
            user_id: 用户 ID

        Returns:
            偏好字典 {key: value}
        """
        with get_db() as db:
            preferences = db.query(UserPreference).filter(UserPreference.user_id == user_id).all()

            return {p.preference_key: p.preference_value for p in preferences}

    def delete_preference(self, user_id: str, preference_key: str) -> bool:
        """
        删除用户偏好

        Args:
            user_id: 用户 ID
            preference_key: 偏好键

        Returns:
            是否删除成功
        """
        with get_db() as db:
            _lock_preference_write(db, user_id, preference_key)
            result = (
                db.query(UserPreference)
                .filter(
                    UserPreference.user_id == user_id,
                    UserPreference.preference_key == preference_key,
                )
                .delete()
            )

            db.commit()
            return cast("bool", result > 0)


def get_user_preference_service() -> UserPreferenceService:
    """获取用户偏好服务单例"""
    return get_service_registry().user_preference_service


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(
    UserPreferenceService, "app.domain.shared_services.user_preference_service"
)
