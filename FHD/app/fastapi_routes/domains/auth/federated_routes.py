"""OIDC and QR sign-in handshakes."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Body, Query, Request
from fastapi.background import BackgroundTasks

from .federated_login import FederatedLogin
from .ports import JsonObject


class FederatedRoutes:
    """OIDC and QR sign-in handshakes."""

    def __init__(self, *, federated: Callable[[], FederatedLogin]) -> None:
        router = self.router = APIRouter()

        @router.get("/api/auth/oidc/status", response_model=None)
        def auth_oidc_status() -> object:
            return federated().oidc_status()

        self.auth_oidc_status = auth_oidc_status

        @router.get("/api/auth/oidc/start", response_model=None)
        async def auth_oidc_start(request: Request) -> object:
            return await federated().oidc_start(request)

        self.auth_oidc_start = auth_oidc_start

        @router.get("/api/auth/oidc/callback", response_model=None)
        async def auth_oidc_callback(
            request: Request, background_tasks: BackgroundTasks = cast(BackgroundTasks, None)
        ) -> object:
            return await federated().oidc_callback(request, background_tasks)

        self.auth_oidc_callback = auth_oidc_callback

        @router.post("/api/auth/qr/issue", response_model=None)
        async def auth_qr_issue(
            request: Request, body: JsonObject = Body(default_factory=dict)
        ) -> object:
            return await federated().qr_issue(request, body)

        self.auth_qr_issue = auth_qr_issue

        @router.get("/api/auth/qr/status", response_model=None)
        async def auth_qr_status(qr_id: str = Query(""), poll_secret: str = Query("")) -> object:
            return await federated().qr_status(qr_id, poll_secret)

        self.auth_qr_status = auth_qr_status
