"""租户权益策略实现。

T-E03 交付物（G1 + G3）：
- ``Decision``：策略判定的不可变结果。
- ``TenantEntitlementPolicy``：所有租户级权益策略的 ABC。
- ``TenantModAccessPolicy``：第一条具体策略，判定 ``access_mod`` 动作。

设计要点：
- MVP 阶段 ``tenant_id`` 退化为 ``user_id``（软租户），避免引入 Tenant 表的大迁移。
- 数据源是 ``UserMod`` 表（与 FHD 桌面端 ``app/enterprise/mod_entitlements.py`` 一致）。
- 策略失败时返回 ``Decision.deny_with(...)`` 而非抛异常，避免拖垮请求路由层。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    """策略判定结果（不可变）。

    - ``allow``：是否允许动作。
    - ``reason``：人类可读的理由（用于审计日志与排错）。
    - ``metadata``：附加信息（如命中的策略版本、检查耗时），不参与相等性判定。
    """

    allow: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow_with(cls, reason: str = "", **metadata: Any) -> "Decision":
        return cls(allow=True, reason=reason, metadata=metadata)

    @classmethod
    def deny_with(cls, reason: str = "", **metadata: Any) -> "Decision":
        return cls(allow=False, reason=reason, metadata=metadata)


class TenantEntitlementPolicy(ABC):
    """租户级权益策略的统一接口。

    所有具体策略（Mod 访问、成本上限、配额上限、审计日志等）都实现此接口，
    便于在请求路由层统一调用 ``check(tenant_id, action, resource)``。

    ``tenant_id`` 在 MVP 阶段退化为 ``user_id``（软租户），等 G2 Tenant 表落地
    后再切换为真实租户 ID。策略实现不应假设 ``tenant_id`` 等于 ``user_id``，
    但当前唯一具体策略 ``TenantModAccessPolicy`` 在 MVP 阶段按 ``user_id`` 查询。
    """

    @abstractmethod
    def check(self, tenant_id: int, action: str, resource: str) -> Decision:
        """判定 ``tenant_id`` 是否可以对 ``resource`` 执行 ``action``。

        返回 ``Decision(allow=True/False, reason=...)``；任何异常都应被捕获
        并转为 ``Decision.deny_with("policy evaluation error: ...")``，不应抛出。
        """


class TenantModAccessPolicy(TenantEntitlementPolicy):
    """租户级 Mod 访问策略（G3 具体实现）。

    判定 ``access_mod`` 动作：tenant_id（MVP 退化 = user_id）是否已购买/安装该 Mod。

    数据源：``UserMod`` 表。FHD 桌面端 ``app/enterprise/mod_entitlements.py``
    也读这张表，确保桌面端安装时与云端判定一致。

    边界处理：
    - 不支持的 ``action`` → deny
    - 空 ``resource``（mod_id）→ deny
    - 无效 ``tenant_id``（<=0 或非 int）→ deny
    - DB 查询异常 → deny（不抛异常，记录日志）
    """

    ACTION_ACCESS_MOD = "access_mod"

    def __init__(self, session_factory: Callable[[], Session] | sessionmaker) -> None:
        self._session_factory = session_factory

    def check(self, tenant_id: int, action: str, resource: str) -> Decision:
        if action != self.ACTION_ACCESS_MOD:
            return Decision.deny_with(
                f"unsupported action: {action!r} (supported: {self.ACTION_ACCESS_MOD!r})",
                action=action,
            )

        mod_id = (resource or "").strip()
        if not mod_id:
            return Decision.deny_with("mod_id is empty", action=action)

        try:
            tid = int(tenant_id)
        except (TypeError, ValueError):
            return Decision.deny_with(
                f"tenant_id is not a valid int: {tenant_id!r}",
                action=action,
                tenant_id=tenant_id,
            )
        if tid <= 0:
            return Decision.deny_with(
                f"tenant_id must be positive: {tid}",
                action=action,
                tenant_id=tid,
            )

        try:
            from modstore_server.models import UserMod

            with self._session_factory() as session:
                row = (
                    session.query(UserMod)
                    .filter(UserMod.user_id == tid, UserMod.mod_id == mod_id)
                    .first()
                )
        except SQLAlchemyError as exc:
            logger.exception(
                "TenantModAccessPolicy db error for tenant=%s mod=%s", tid, mod_id
            )
            return Decision.deny_with(
                f"policy evaluation error: {exc.__class__.__name__}",
                action=action,
                mod_id=mod_id,
                tenant_id=tid,
            )
        except Exception as exc:  # noqa: BLE001 — 策略层兜底，绝不向上抛
            logger.exception(
                "TenantModAccessPolicy unexpected error for tenant=%s mod=%s", tid, mod_id
            )
            return Decision.deny_with(
                f"policy evaluation error: {exc.__class__.__name__}",
                action=action,
                mod_id=mod_id,
                tenant_id=tid,
            )

        if row is None:
            return Decision.deny_with(
                f"entitlement not found: tenant_id={tid} has no UserMod row for mod_id={mod_id!r}",
                action=action,
                mod_id=mod_id,
                tenant_id=tid,
            )

        return Decision.allow_with(
            f"UserMod(user_id={tid}, mod_id={mod_id!r}) exists",
            action=action,
            mod_id=mod_id,
            tenant_id=tid,
            user_mod_id=row.id,
        )


__all__ = ["Decision", "TenantEntitlementPolicy", "TenantModAccessPolicy"]
