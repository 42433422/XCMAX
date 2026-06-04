"""XCMAX 同步网关。"""

from __future__ import annotations

from typing import Any


def push_outbox(*args: Any, **kwargs: Any) -> Any:
    from app.services.xcmax_sync_service import push_outbox as _f

    return _f(*args, **kwargs)


def apply_inbox(*args: Any, **kwargs: Any) -> Any:
    from app.services.xcmax_sync_service import apply_inbox as _f

    return _f(*args, **kwargs)


def pull_from_remote(*args: Any, **kwargs: Any) -> Any:
    from app.services.xcmax_sync_service import pull_from_remote as _f

    return _f(*args, **kwargs)


def get_entity_appliers() -> Any:
    from app.services.xcmax_sync_service import _ENTITY_APPLIERS

    return _ENTITY_APPLIERS


__all__ = ["push_outbox", "apply_inbox", "pull_from_remote", "get_entity_appliers"]
