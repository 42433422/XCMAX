"""FastAPI ``Depends`` helpers bound to ``request.app.state.services``."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Request

from app.di.registry import ServiceContainer, get_service_registry


def get_service_container(request: Request) -> ServiceContainer:
    c = getattr(request.app.state, "services", None)
    if c is None:
        return get_service_registry()
    return cast("ServiceContainer", c)


ServiceContainerDep = Annotated[ServiceContainer, get_service_container]
