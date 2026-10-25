"""Account registration and password or phone-code entry."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Body, Request
from fastapi.background import BackgroundTasks

from .credential_login import CredentialLogin
from app.domain.auth.ports import JsonObject
from .registration import Registration


class CredentialRoutes:
    """Account registration and password or phone-code entry."""

    def __init__(
        self,
        *,
        registration: Callable[[], Registration],
        credentials: Callable[[], CredentialLogin],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/api/auth/register", response_model=None)
        async def auth_register(
            request: Request, body: JsonObject = Body(default_factory=dict)
        ) -> object:
            """Register locally (PostgreSQL users) and optionally on Xiuci market; then create session."""
            return await registration().register(request, body)

        self.auth_register = auth_register

        @router.post("/api/auth/login", response_model=None)
        async def auth_login(
            request: Request,
            body: JsonObject = Body(default_factory=dict),
            background_tasks: BackgroundTasks = cast(BackgroundTasks, None),
        ) -> object:
            return await credentials().password(request, body, background_tasks)

        self.auth_login = auth_login

        @router.post("/api/auth/login-with-phone-code", response_model=None)
        async def auth_login_with_phone_code(
            request: Request,
            body: JsonObject = Body(default_factory=dict),
            background_tasks: BackgroundTasks = cast(BackgroundTasks, None),
        ) -> object:
            return await credentials().phone_code(request, body, background_tasks)

        self.auth_login_with_phone_code = auth_login_with_phone_code
