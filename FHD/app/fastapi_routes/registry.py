"""Declarative FastAPI route registry with deduplication and conflict detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

logger = logging.getLogger(__name__)


@dataclass
class RouteMount:
    """Single router mount entry."""

    name: str
    router: APIRouter
    priority: int = 100
    prefix: str | None = None
    tags: list[str] | None = None
    edition: set[str] = field(default_factory=lambda: {"full", "minimal", "generic"})
    required: bool = False
    include_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteConflict:
    """Duplicate method+path detected across mounts."""

    method: str
    path: str
    mounts: list[str]


class RouteRegistry:
    """Collects route mounts, deduplicates by name, applies in priority order."""

    def __init__(self) -> None:
        self._mounts: dict[str, RouteMount] = {}

    def register(self, mount: RouteMount) -> None:
        if mount.name in self._mounts:
            logger.warning("Duplicate route mount ignored: %s", mount.name)
            return
        self._mounts[mount.name] = mount

    def register_router(
        self,
        name: str,
        router: APIRouter,
        *,
        priority: int = 100,
        prefix: str | None = None,
        tags: list[str] | None = None,
        required: bool = False,
        **include_kwargs: Any,
    ) -> None:
        self.register(
            RouteMount(
                name=name,
                router=router,
                priority=priority,
                prefix=prefix,
                tags=tags,
                required=required,
                include_kwargs=include_kwargs,
            )
        )

    def apply(self, app: FastAPI) -> None:
        for mount in sorted(self._mounts.values(), key=lambda m: (m.priority, m.name)):
            kwargs: dict[str, Any] = dict(mount.include_kwargs)
            if mount.prefix is not None:
                kwargs.setdefault("prefix", mount.prefix)
            if mount.tags is not None:
                kwargs.setdefault("tags", mount.tags)
            app.include_router(mount.router, **kwargs)
            logger.info(
                "RouteRegistry applied %s (priority=%d, routes=%d)",
                mount.name,
                mount.priority,
                len(mount.router.routes),
            )

    def detect_conflicts(self) -> list[RouteConflict]:
        """Detect duplicate (method, path) pairs across registered routers."""
        seen: dict[tuple[str, str], list[str]] = {}
        for mount in self._mounts.values():
            for route in mount.router.routes:
                if isinstance(route, Route):
                    for method in route.methods or {"GET"}:
                        key = (method.upper(), route.path)
                        seen.setdefault(key, []).append(mount.name)
        conflicts: list[RouteConflict] = []
        for (method, path), mounts in sorted(seen.items()):
            if len(mounts) > 1:
                conflicts.append(RouteConflict(method=method, path=path, mounts=mounts))
        return conflicts

    def names(self) -> list[str]:
        return sorted(self._mounts.keys())

    def clear(self) -> None:
        self._mounts.clear()
