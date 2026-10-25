"""Lazy adapters to existing local services; components receive these as ports."""

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.orm import Session

from .port_contracts import JsonObject, LocalUser

if TYPE_CHECKING:
    from app.db.models.user import Session as UserSession


def database() -> AbstractContextManager[Session]:
    from app.db.session import get_db

    return get_db()


def session_model() -> type["UserSession"]:
    from app.db.models.user import Session as UserSession

    return UserSession


def current_user(request: Request) -> LocalUser | None:
    from app.infrastructure.auth.dependencies import resolve_session_user

    return resolve_session_user(request)


async def sync_entitlements(session_id: str) -> set[str]:
    from app.enterprise.mod_entitlements import sync_entitlements_for_session

    return await sync_entitlements_for_session(session_id)


def is_demo_token(token: str) -> bool:
    from app.application.surface_audit_demo_account import is_local_demo_market_token

    return is_local_demo_market_token(token)


def try_demo_login(username: str, password: str) -> JsonObject | None:
    from app.application.surface_audit_demo_account import try_local_demo_market_login

    return try_local_demo_market_login(username, password)


def industry_seed(industry_id: str) -> str | None:
    from app.mod_sdk.industry_seed import industry_mod_id_for

    return industry_mod_id_for(industry_id)


def industry_alias(industry_id: str) -> str:
    from app.mod_sdk.industry_mod_aliases import canonical_mod_id_for_industry

    return canonical_mod_id_for_industry(industry_id)


def deliveries(industry_id: str) -> list[JsonObject]:
    from app.mod_sdk.customer_delivery import deliveries_for_industry

    return deliveries_for_industry(industry_id)


def session_meta(session_id: str) -> JsonObject | None:
    from app.application.session_account_meta import load_session_account_meta

    return load_session_account_meta(session_id)


def claim_user_id(token: str) -> int | None:
    from app.enterprise.mod_entitlements import _market_user_id_from_access_token

    return _market_user_id_from_access_token(token)
