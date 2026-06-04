"""XCMAX 同步应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import sync as sync_gw


def push_outbox(*args: Any, **kwargs: Any) -> Any:
    return sync_gw.push_outbox(*args, **kwargs)


def apply_inbox(*args: Any, **kwargs: Any) -> Any:
    return sync_gw.apply_inbox(*args, **kwargs)


def pull_from_remote(*args: Any, **kwargs: Any) -> Any:
    return sync_gw.pull_from_remote(*args, **kwargs)


def get_entity_appliers() -> Any:
    return sync_gw.get_entity_appliers()
