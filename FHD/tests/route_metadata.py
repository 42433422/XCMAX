"""Path-contract views without rebuilding API dependency validators.

Keep the production materializer for runtime/schema mutation. Non-API included
routes retain its context view (not an expanded Mount or WebSocket path).
"""

from dataclasses import replace

from fastapi.routing import APIRoute, _IncludedRouter
from starlette.routing import Host, Mount, Route, WebSocketRoute

from app.legacy.routes.openapi_route_compat import EffectiveRoute, _route_view


def _included_metadata(branch, *, prefix):
    if branch._effective_candidates_version == branch.original_router._get_routes_version():
        # Preserve app-local alias removals and already-combined include metadata.
        for candidate in branch._effective_candidates:
            if isinstance(candidate, _IncludedRouter):
                yield from _included_metadata(candidate, prefix=prefix)
            else:
                yield _route_view(candidate, prefix=prefix)
        return
    context = branch.include_context
    for route in branch.original_router.routes:
        if isinstance(route, _IncludedRouter):
            child = _IncludedRouter(
                original_router=route.original_router,
                include_context=context.combine(route.include_context),
            )
            yield from _included_metadata(child, prefix=prefix)
        elif isinstance(route, APIRoute):
            view = _route_view(route, prefix=prefix + context.prefix)
            yield replace(
                view,
                tags=[*context.tags, *(view.tags or [])],
                include_in_schema=context.include_in_schema and view.include_in_schema,
            )
        elif isinstance(route, (Route, WebSocketRoute, Mount, Host)):
            # These included routes expose the default _EffectiveRouteContext
            # fields to the existing materializer. Do not construct their
            # runtime wrappers: WebSocket wrappers rebuild parameter validators.
            yield EffectiveRoute(
                source=route,
                path=prefix,
                methods=set(),
                endpoint=None,
                include_in_schema=True,
                tags=[],
                original_route=route,
            )
        else:
            raise AssertionError(f"Unsupported included route metadata: {type(route).__name__}")


def iter_route_metadata(routes, *, prefix=""):
    for route in routes:
        if isinstance(route, _IncludedRouter):
            yield from _included_metadata(route, prefix=prefix)
        elif isinstance(route, Mount):
            yield from iter_route_metadata(route.routes, prefix=prefix + route.path)
        else:
            yield _route_view(route, prefix=prefix)
