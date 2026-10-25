"""Typed boundaries used by the independent authentication route components."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol, TypeAlias

from fastapi import BackgroundTasks, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.application.session_account_meta import AccountKind
from app.db.models.user import User

JsonObject: TypeAlias = dict[str, Any]
RouteResult: TypeAlias = JsonObject | Response
Database: TypeAlias = Callable[[], AbstractContextManager[Session]]
ErrorTypes: TypeAlias = Callable[[], tuple[type[Exception], ...]]
MarketPasswordLogin: TypeAlias = Callable[[str, str], Awaitable[JsonObject]]
JitCreate: TypeAlias = Callable[[str, str, str], bool]
AttachCookie: TypeAlias = Callable[[Response, str | None], Response]


class PublicUser(Protocol):
    """The fields needed to project a user, independent of persistence."""

    @property
    def id(self) -> int: ...

    @property
    def username(self) -> str: ...

    @property
    def display_name(self) -> str | None: ...

    @property
    def email(self) -> str | None: ...

    @property
    def role(self) -> str: ...

    @property
    def is_active(self) -> bool | None: ...


class SessionInspector(Protocol):
    def get_session_info(self, session_id: str) -> JsonObject | None: ...


class SessionBackend(Protocol):
    @property
    def session_manager(self) -> SessionInspector: ...

    def get_user_permissions(self, user: User) -> list[str]: ...

    def logout(self, session_id: str) -> bool: ...


class PasswordBackend(Protocol):
    def change_password(self, user_id: int, old_password: str, new_password: str) -> JsonObject: ...

    def reset_password(self, user_id: int, new_password: str) -> JsonObject: ...


class LoginBackend(Protocol):
    def login(
        self,
        username: str,
        password: str,
        *,
        totp_code: str | None = None,
        enforce_mfa: bool = True,
    ) -> JsonObject: ...

    def create_session_for_username(self, username: str) -> JsonObject: ...

    def authenticate_oidc_user(self, profile: JsonObject) -> JsonObject: ...


class UserDirectory(Protocol):
    def get_user(self, user_id: int) -> JsonObject | None: ...

    def list_users(self, skip: int = 0, limit: int = 100) -> list[JsonObject]: ...

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
        email: str = "",
        role: str = "user",
    ) -> JsonObject: ...

    def update_user(
        self,
        user_id: int,
        display_name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> JsonObject: ...

    def delete_user(self, user_id: int) -> JsonObject: ...


class RegistrationEnricher(Protocol):
    def __call__(
        self,
        *,
        result: JsonObject,
        username: str,
        session_id: str | None,
        sku: str,
        company_brand: str = "",
    ) -> JsonObject: ...


class MarketFirstLogin(Protocol):
    def __call__(
        self,
        *,
        username: str,
        password: str | None,
        account_kind: AccountKind,
        market_result: JsonObject | None,
        auth_app_service: LoginBackend,
        sku: str,
        jit_create_fn: JitCreate,
        market_user_email_from_raw: Callable[[object], str],
        login_market_fn: MarketPasswordLogin | None = None,
        totp_code: str | None = None,
        invitation_code: str = "",
        background_tasks: BackgroundTasks | None = None,
    ) -> Awaitable[tuple[JsonObject | None, JSONResponse | None]]: ...


class FinalizeOidc(Protocol):
    def __call__(
        self,
        *,
        auth_result: JsonObject,
        oidc_profile: JsonObject,
        oidc_access_token: str = "",
        account_kind: AccountKind,
        sku: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> Awaitable[JsonObject]: ...


class QrIssuer(Protocol):
    def __call__(
        self, *, client_hint: str = "", account_kind: str = "enterprise"
    ) -> JsonObject: ...
