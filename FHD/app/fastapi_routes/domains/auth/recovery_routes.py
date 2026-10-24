"""Account lookup and verified password recovery."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Body

from .account_recovery import AccountRecovery
from .ports import JsonObject


class RecoveryRoutes:
    """Account lookup and verified password recovery."""

    def __init__(self, *, recovery: Callable[[], AccountRecovery]) -> None:
        router = self.router = APIRouter()

        @router.post("/api/auth/forgot-account", response_model=None)
        def auth_forgot_account(body: JsonObject = Body(default_factory=dict)) -> object:
            """Look up local PostgreSQL users by email (same DB as login)."""
            return recovery().find_account(body)

        self.auth_forgot_account = auth_forgot_account

        @router.post("/api/auth/forgot-password/send-code", response_model=None)
        async def auth_forgot_password_send_code(
            body: JsonObject = Body(default_factory=dict),
        ) -> object:
            """Send reset code via Xiuci market API; uses XCAGI_MARKET_BASE_URL (e.g. production server)."""
            return await recovery().send_code(body)

        self.auth_forgot_password_send_code = auth_forgot_password_send_code

        @router.post("/api/auth/forgot-password/reset", response_model=None)
        async def auth_forgot_password_reset(
            body: JsonObject = Body(default_factory=dict),
        ) -> object:
            """Reset password on market, then sync matching users in local PostgreSQL."""
            return await recovery().reset_password(body)

        self.auth_forgot_password_reset = auth_forgot_password_reset
