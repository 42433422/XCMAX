"""Document-level access control inside one tenant.

租户隔离仍是硬边界；ACL 只在该租户内按主体（actor）进一步收窄可见范围。
文档元数据键为 ``acl``，形如 ``{"allow_actors": [...], "deny_actors": [...]}``。
"""

from __future__ import annotations

from typing import Any

from app.application.dataset_rag.access_policy import (
    DATASET_ADMIN_PERMISSION,
    _coerce_access_context,
)
from app.application.dataset_rag.models import DatasetAccessContext

ACL_METADATA_KEY = "acl"
ACL_ALLOW_ACTORS = "allow_actors"
ACL_DENY_ACTORS = "deny_actors"
_ACL_KEYS = frozenset({ACL_ALLOW_ACTORS, ACL_DENY_ACTORS})
_MAX_PRINCIPALS = 200
_MAX_PRINCIPAL_LENGTH = 160


def normalize_document_acl(value: Any) -> dict[str, list[str]]:
    """校验并归一化 ACL；非法输入抛 ValueError，空值返回空字典。"""
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise ValueError("acl must be an object")
    unknown = set(value) - _ACL_KEYS
    if unknown:
        raise ValueError(f"unsupported acl keys: {', '.join(sorted(map(str, unknown)))}")
    normalized: dict[str, list[str]] = {}
    for key in (ACL_ALLOW_ACTORS, ACL_DENY_ACTORS):
        raw = value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"acl.{key} must be a list of actor ids")
        seen: dict[str, None] = {}
        for item in raw:
            principal = str(item).strip()
            if not principal:
                continue
            if len(principal) > _MAX_PRINCIPAL_LENGTH:
                raise ValueError(f"acl.{key} entry is too long")
            seen.setdefault(principal, None)
        if len(seen) > _MAX_PRINCIPALS:
            raise ValueError(f"acl.{key} cannot exceed {_MAX_PRINCIPALS} entries")
        if seen:
            normalized[key] = list(seen)
    return normalized


def document_acl(metadata: dict[str, Any] | None) -> dict[str, list[str]]:
    return normalize_document_acl((metadata or {}).get(ACL_METADATA_KEY))


def document_visible_to(
    metadata: dict[str, Any] | None,
    access_context: DatasetAccessContext | dict[str, Any] | None,
) -> bool:
    """判断文档是否对当前主体可见；无 ACL 时保持租户级默认可见。"""
    acl = document_acl(metadata)
    if not acl:
        return True
    context = _coerce_access_context(access_context)
    # 系统内部调用（没有主体上下文）沿用既有行为；HTTP 入口始终带上下文。
    if context is None:
        return True
    if context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        return True
    actor = str(context.actor_id or "").strip()
    denied = acl.get(ACL_DENY_ACTORS) or []
    if actor and actor in denied:
        return False
    allowed = acl.get(ACL_ALLOW_ACTORS) or []
    if allowed:
        return bool(actor) and actor in allowed
    return True


def filter_chunks_by_acl(
    chunks: list[Any],
    access_context: DatasetAccessContext | dict[str, Any] | None,
) -> list[Any]:
    return [
        chunk
        for chunk in chunks
        if document_visible_to(getattr(chunk, "metadata", None) or {}, access_context)
    ]
