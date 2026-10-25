"""Session identity, token lifecycle and subscription visibility."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Body, Request
from fastapi.background import BackgroundTasks

from app.domain.auth.ports import JsonObject

from .session_access import SessionAccess


class SessionRoutes:
    """Session identity, token lifecycle and subscription visibility."""

    def __init__(self, *, sessions: Callable[[], SessionAccess]) -> None:
        router = self.identity = APIRouter()

        @router.get("/api/auth/me", response_model=None)
        def auth_me(request: Request) -> object:
            return sessions().current_user(request)

        self.auth_me = auth_me

        router = self.tokens = APIRouter()

        @router.post("/api/auth/token/refresh", response_model=None)
        def auth_token_refresh(body: JsonObject = Body(default_factory=dict)) -> object:
            """无状态 JWT：用 refresh token 轮转出新的 access/refresh（一次性使用）。"""
            return sessions().refresh(body)

        self.auth_token_refresh = auth_token_refresh

        @router.get("/api/auth/session/validate", response_model=None)
        async def auth_session_validate(
            request: Request, background_tasks: BackgroundTasks
        ) -> object:
            return await sessions().validate(request, background_tasks)

        self.auth_session_validate = auth_session_validate

        @router.get("/api/runtime/product-sku", response_model=None)
        def runtime_product_sku() -> object:
            return sessions().runtime_sku()

        self.runtime_product_sku = runtime_product_sku

        @router.get("/api/auth/subscription/status", response_model=None)
        def auth_subscription_status(request: Request) -> object:
            """当前登录用户的试用/付费订阅状态（SaasPricingView 与订阅门禁共用）。"""
            return sessions().subscription_status(request)

        self.auth_subscription_status = auth_subscription_status

        router = self.logout = APIRouter()

        @router.post("/api/auth/logout", response_model=None)
        def auth_logout(request: Request) -> object:
            return sessions().logout(request)

        self.auth_logout = auth_logout
