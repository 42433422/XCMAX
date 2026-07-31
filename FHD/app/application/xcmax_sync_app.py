"""XCMAX 同步应用层门面。"""

from __future__ import annotations

from typing import Any


def push_outbox(*, remote_host: str, remote_port: int) -> Any:
    from app.services.xcmax_sync_service import push_outbox as _push

    return _push(remote_host=remote_host, remote_port=remote_port)


def record_change(
    entity_type: str,
    entity_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    actor: str = "system",
    version: int = 1,
) -> int:
    from app.services.xcmax_sync_service import record_change as _record

    return _record(
        entity_type,
        entity_id,
        operation,
        payload,
        actor=actor,
        version=version,
    )


def apply_inbox(limit: int = 200, **kwargs: Any) -> Any:
    from app.application.private_mod import delivery_applier as private_mod_delivery_applier  # noqa: F401
    from app.services.xcmax_sync_service import apply_inbox as _apply

    return _apply(limit=limit, **kwargs)


def pull_from_remote(*, remote_host: str, remote_port: int, **kwargs: Any) -> Any:
    from app.services.xcmax_sync_service import pull_from_remote as _pull

    return _pull(remote_host=remote_host, remote_port=remote_port, **kwargs)


def read_sync_meta(key: str) -> dict[str, Any]:
    from app.services.xcmax_sync_service import _read_sync_meta

    return _read_sync_meta(key)


def entity_appliers():
    from app.services.xcmax_sync_service import _ENTITY_APPLIERS

    return _ENTITY_APPLIERS
