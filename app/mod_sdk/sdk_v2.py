"""XCAGI Mod SDK 2.0 — 面向 Mod 作者的稳定契约入口。

在 1.x 的基础上提供更好的 manifest / hook / comms：

- ``@on_event`` 事件订阅装饰器（支持 priority / once）
- ``build_manifest`` manifest 构造器，校验 SDK 2.0 字段（双发布 / 能力 / 兼容区间）
- ``publish_event`` 经 NeuroBus 桥发布事件，与宿主事件总线对齐
- 透传 ``comms`` 的 ``register`` / ``call`` 进行 Mod 间通信

Mod 代码只应 ``from app.mod_sdk.sdk_v2 import ...``，不直接依赖 ``app.infrastructure.*``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.infrastructure.mods.artifact_constants import (
    ARTIFACT_AI,
    ARTIFACT_MOD,
    RELEASE_TARGET_AI,
    RELEASE_TARGET_MOD,
)
from app.infrastructure.mods.hooks import (
    get_hook_manager,
    subscribe,
    trigger,
    trigger_collect,
)
from app.infrastructure.mods.manifest import CURRENT_SDK_VERSION

logger = logging.getLogger(__name__)


def on_event(event: str, *, priority: int = 100, once: bool = False, mod_id: str = "") -> Callable:
    """事件订阅装饰器（SDK 2.0）。

    用法::

        @on_event("order.created", priority=10)
        def handle_order(order): ...
    """

    def decorator(func: Callable) -> Callable:
        subscribe(event, func, priority=priority, once=once, mod_id=mod_id)
        return func

    return decorator


def emit(event: str, *args: Any, **kwargs: Any) -> None:
    """触发 hook 事件（不收集返回值）。"""
    trigger(event, *args, **kwargs)


def emit_collect(event: str, *args: Any, **kwargs: Any) -> list[Any]:
    """触发 hook 事件并收集各订阅者返回值（按优先级顺序）。"""
    return trigger_collect(event, *args, **kwargs)


class ManifestError(ValueError):
    """manifest 校验失败。"""


def build_manifest(
    *,
    id: str,
    name: str,
    version: str,
    author: str = "",
    description: str = "",
    release_targets: list[str] | None = None,
    capabilities: list[str] | None = None,
    min_host_version: str = "",
    max_host_version: str = "",
    ai_manifest: dict[str, Any] | None = None,
    backend: dict[str, Any] | None = None,
    frontend: dict[str, Any] | None = None,
    hooks: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造并校验一个 SDK 2.0 manifest dict（可 json.dump 写入 manifest.json）。

    校验：必填字段、release_targets 合法、ai 双发布时必须提供 ai_manifest。
    """
    if not id or not name or not version:
        raise ManifestError("id / name / version 为必填")
    targets = release_targets or [RELEASE_TARGET_MOD]
    for t in targets:
        if t not in (RELEASE_TARGET_MOD, RELEASE_TARGET_AI):
            raise ManifestError(f"非法 release_target: {t}")
    if RELEASE_TARGET_AI in targets and not (ai_manifest or {}):
        raise ManifestError("release_targets 含 'ai' 时必须提供 ai_manifest")

    artifact = ARTIFACT_AI if targets == [RELEASE_TARGET_AI] else ARTIFACT_MOD
    manifest: dict[str, Any] = {
        "sdk_version": CURRENT_SDK_VERSION,
        "id": id,
        "name": name,
        "version": version,
        "author": author,
        "description": description,
        "artifact": artifact,
        "release_targets": targets,
        "capabilities": capabilities or [],
    }
    if min_host_version or max_host_version:
        manifest["compat"] = {
            "min_host_version": min_host_version,
            "max_host_version": max_host_version,
        }
    if ai_manifest:
        manifest["ai"] = ai_manifest
    if backend:
        manifest["backend"] = backend
    if frontend:
        manifest["frontend"] = frontend
    if hooks:
        manifest["hooks"] = hooks
    if extra:
        manifest.update(extra)
    return manifest


def publish_event(domain: str, event_type: str, payload: dict[str, Any]) -> bool:
    """经 NeuroBus 发布业务事件（comms 对齐宿主事件总线）。

    成功返回 True；NeuroBus 不可用时回落到本地 hook（``emit``）并返回 False。
    """
    try:
        from app.mod_sdk.neuro_bus_compat import is_neuro_bus_via_mod_enabled

        if is_neuro_bus_via_mod_enabled():
            from app.mod_sdk.neuro_bus_runtime import publish as _bus_publish  # type: ignore

            _bus_publish(domain=domain, event_type=event_type, payload=payload)
            return True
    except Exception as exc:
        logger.debug("publish_event via NeuroBus failed, fallback to hook: %s", exc)
    emit(f"{domain}.{event_type}", payload)
    return False


__all__ = [
    "on_event",
    "emit",
    "emit_collect",
    "build_manifest",
    "publish_event",
    "ManifestError",
    "get_hook_manager",
    "ARTIFACT_MOD",
    "ARTIFACT_AI",
    "RELEASE_TARGET_MOD",
    "RELEASE_TARGET_AI",
    "CURRENT_SDK_VERSION",
]
