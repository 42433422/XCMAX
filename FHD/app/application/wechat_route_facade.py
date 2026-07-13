"""Application boundary for WeChat compatibility routes."""

from __future__ import annotations

from typing import Any


def _call(module_name: str, function_name: str, *args: Any, **kwargs: Any) -> Any:
    from importlib import import_module

    function = getattr(import_module(module_name), function_name)
    return function(*args, **kwargs)


def assert_safe_outbound_group_reply(*args: Any, **kwargs: Any) -> str:
    return _call(
        "app.services.wechat_passive_group_monitor",
        "assert_safe_outbound_group_reply",
        *args,
        **kwargs,
    )


def probe_passive_llm_ready(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_passive_group_monitor", "probe_passive_llm_ready", *args, **kwargs
    )


def passive_poll_once(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call("app.services.wechat_passive_group_monitor", "passive_poll_once", *args, **kwargs)


def get_passive_poll_config(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_passive_group_monitor", "get_passive_poll_config", *args, **kwargs
    )


def save_passive_poll_config(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_passive_group_monitor", "save_passive_poll_config", *args, **kwargs
    )


def reset_passive_watch(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_passive_group_monitor", "reset_passive_watch", *args, **kwargs
    )


def build_starred_group_feed(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return _call(
        "app.services.wechat_group_customer_bridge", "build_starred_group_feed", *args, **kwargs
    )


def sync_group_messages(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_group_customer_bridge", "sync_group_messages", *args, **kwargs
    )


def sync_bound_groups_from_live_wechat(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call(
        "app.services.wechat_group_customer_bridge",
        "sync_bound_groups_from_live_wechat",
        *args,
        **kwargs,
    )


def latest_context_message(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    return _call(
        "app.services.wechat_group_customer_bridge", "_latest_context_message", *args, **kwargs
    )


def list_group_contacts(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return _call(
        "app.services.wechat_group_customer_bridge", "list_group_contacts", *args, **kwargs
    )


def prepare_wechat_message_db_for_read(*args: Any, **kwargs: Any) -> Any:
    from importlib import import_module

    function = getattr(
        import_module("app.services.wechat_decrypt_autoconfig"),
        "prepare_wechat_message_db_for_read",
        None,
    )
    if not callable(function):
        return {"configured": False, "message": "wechat decrypt preparation is unavailable"}
    return function(*args, **kwargs)


__all__ = [name for name in globals() if not name.startswith("_") and name not in {"Any"}]
