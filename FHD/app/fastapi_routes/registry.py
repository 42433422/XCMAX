"""Declarative FastAPI route registry with deduplication and conflict detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI
from starlette.routing import Mount, compile_path

from app.legacy.routes.openapi_route_compat import iter_effective_routes

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
    """An exact duplicate or a static path shadowed by an earlier parameter route."""

    method: str
    path: str
    mounts: list[str]
    kind: str = "duplicate"
    shadowed_by: str | None = None


def _detect_conflicts(entries) -> list[RouteConflict]:
    seen: dict[tuple[str, str], list[str]] = {}
    dynamic: list[tuple[re.Pattern[str], str, set[str] | None, str]] = []
    conflicts: list[RouteConflict] = []
    for route, owner in entries:
        if isinstance(route.original_route, Mount):
            pattern, _, _ = compile_path(route.path.rstrip("/") + "/{path:path}")
            dynamic.append((pattern, route.path, None, f"mount:{route.path}"))
            continue
        if not route.path or not route.methods:
            continue
        methods = {str(method).upper() for method in route.methods}
        for method in methods:
            seen.setdefault((method, route.path), []).append(owner)
        pattern, _format, converters = compile_path(route.path)
        if converters:
            dynamic.append((pattern, route.path, methods, owner))
        else:
            for earlier, path, earlier_methods, earlier_owner in dynamic:
                if earlier.fullmatch(route.path):
                    for method in sorted(
                        methods if earlier_methods is None else methods & earlier_methods
                    ):
                        conflicts.append(
                            RouteConflict(
                                method, route.path, [earlier_owner, owner], "shadow", path
                            )
                        )
    conflicts[:0] = [
        RouteConflict(method, path, owners)
        for (method, path), owners in sorted(seen.items())
        if len(owners) > 1
    ]
    return conflicts


def detect_app_route_conflicts(app: FastAPI) -> list[RouteConflict]:
    """Inspect the current app, including legacy and already mounted Mod routes."""
    return _detect_conflicts(
        (
            route,
            f"{getattr(route.endpoint, '__module__', '')}:"
            f"{getattr(route.endpoint, '__qualname__', route.name)}",
        )
        for route in iter_effective_routes(app.routes, include_mounts=True)
    )


class RouteRegistry:
    """Collects route mounts, deduplicates by name, applies in priority order."""

    def __init__(self, app: FastAPI | None = None) -> None:
        self._mounts: dict[str, RouteMount] = {}
        self.app = app

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
        """Use the same prefixes and order as apply(), expanding nested includes."""
        return _detect_conflicts(
            (route, mount.name)
            for mount in sorted(self._mounts.values(), key=lambda m: (m.priority, m.name))
            for route in iter_effective_routes(
                mount.router.routes,
                prefix=mount.include_kwargs.get("prefix", mount.prefix) or "",
                include_mounts=True,
            )
        )

    def names(self) -> list[str]:
        return sorted(self._mounts.keys())

    def clear(self) -> None:
        self._mounts.clear()
