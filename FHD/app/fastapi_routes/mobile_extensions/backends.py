"""Concrete mobile I/O adapters. Imports occur at invocation to preserve service replacement."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import Request

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.application.im_app_service import ImApplicationService
    from app.db.xcmax_sync import SyncDb
    from app.fastapi_routes.mod_store.schemas import ModStoreInstallResult
    from app.infrastructure.mods.mod_manager import ModManager


def im_service(db: Session) -> ImApplicationService:
    from app.application.im_app_service import ImApplicationService as operation

    return cast("ImApplicationService", operation(db))


def session_factory() -> Session:
    from app.db import SessionLocal as operation

    return cast("Session", operation())


def sync_database() -> SyncDb:
    from app.db.xcmax_sync import SyncDb as operation

    return cast("SyncDb", operation())


def auth_header(token: str) -> str:
    from app.fastapi_routes.market_account import _auth_header as operation

    return cast("str", operation(token))


def ensure_sync_schema(conn: sqlite3.Connection) -> None:
    from app.db.xcmax_sync import _ensure_schema as operation

    operation(conn)


def sync_connection() -> AbstractContextManager[sqlite3.Connection]:
    from app.db.xcmax_sync import _get_conn as operation

    return cast("AbstractContextManager[sqlite3.Connection]", operation())


async def install_mod(pkg_id: str, version: str, activate: bool = True) -> ModStoreInstallResult:
    from app.fastapi_routes.mod_store_routes import _install_from_catalog as operation

    return cast("ModStoreInstallResult", await operation(pkg_id, version, activate=activate))


async def install_foundation(edition: str | None) -> ModStoreInstallResult:
    from app.fastapi_routes.mod_store_routes import _install_host_foundation_internal as operation

    return cast("ModStoreInstallResult", await operation(edition))


def installed_employee_ids() -> set[str]:
    from app.application.ops_closure_status import _installed_employee_pack_ids as operation

    return cast("set[str]", operation())


def market_base_url() -> str:
    from app.fastapi_routes.market_account import _market_base_url as operation

    return cast("str", operation())


async def market_proxy(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    authorization: str = "",
    return_error_payload: bool = False,
) -> object:
    from app.fastapi_routes.market_account import _proxy_json as operation

    if json_body is None:
        return await operation(
            method, path, authorization=authorization, return_error_payload=return_error_payload
        )
    return await operation(
        method,
        path,
        json_body=json_body,
        authorization=authorization,
        return_error_payload=return_error_payload,
    )


def add_comment(*, post_id: int, user_id: int, author_name: str, body: str) -> int:
    from app.application.ai_circle_service import add_comment as operation

    return cast(
        "int", operation(post_id=post_id, user_id=user_id, author_name=author_name, body=body)
    )


def apply_inbox(*, limit: int) -> dict[str, Any]:
    from app.application.xcmax_sync_app import apply_inbox as operation

    return cast("dict[str, Any]", operation(limit=limit))


def select_industry(user: object, industry_id: str, *, industry_mod_id: str = "") -> dict[str, Any]:
    from app.application.tenant_workspace_prefs import bind_selected_industry_for_user as operation

    return cast("dict[str, Any]", operation(user, industry_id, industry_mod_id=industry_mod_id))


async def industry_plan(request: Request, industry_id: str) -> dict[str, Any]:
    from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request as operation

    return cast("dict[str, Any]", await operation(request, industry_id))


async def industry_catalog(request: Request) -> dict[str, Any]:
    from app.mod_sdk.industry_baseline import (
        build_onboarding_industry_catalog_for_request as operation,
    )

    return cast("dict[str, Any]", await operation(request))


def platform_shell(installed_mod_ids: list[str]) -> dict[str, Any]:
    from app.mod_sdk.platform_shell import build_platform_shell_payload as operation

    return cast("dict[str, Any]", operation(installed_mod_ids))


def cached_relay() -> dict[str, Any] | None:
    from app.application.facades.mobile_relay_facade import (
        cached_desktop_relay_payload as operation,
    )

    return cast("dict[str, Any] | None", operation())


def create_post(*, user_id: int, author_name: str, avatar: str | None, body: str) -> int:
    from app.application.ai_circle_service import create_user_post as operation

    return cast(
        "int", operation(user_id=user_id, author_name=author_name, avatar=avatar, body=body)
    )


def duty_roster() -> dict[str, Any]:
    from app.mod_sdk.employee_ssot import derive_admin_duty_roster as operation

    return cast("dict[str, Any]", operation())


def employee_ssot(*, installed_ids: set[str]) -> dict[str, Any]:
    from app.mod_sdk.employee_ssot import derive_employee_ssot as operation

    return cast("dict[str, Any]", operation(installed_ids=installed_ids))


def execute_employee(
    employee_id: str,
    task: str,
    input_data: dict[str, Any],
    *,
    user_id: int,
    workspace_root: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    from app.application.employee_runtime.executor import execute_employee_task_local as operation

    return cast(
        "dict[str, Any]",
        operation(
            employee_id,
            task,
            input_data,
            user_id=user_id,
            workspace_root=workspace_root,
            session_id=session_id,
        ),
    )


def database() -> AbstractContextManager[Session]:
    from app.db.session import get_db as operation

    return cast("AbstractContextManager[Session]", operation())


def mod_manager() -> ModManager:
    from app.infrastructure.mods.mod_manager import get_mod_manager as operation

    return cast("ModManager", operation())


async def grant_entitlements(session_id: str, industry_id: str) -> dict[str, Any]:
    from app.fastapi_routes.market_account import (
        grant_market_enterprise_entitlements_for_session as operation,
    )

    return cast("dict[str, Any]", await operation(session_id, industry_id))


async def install_customer_seed(
    *, request: Request, mod_id: str, industry_id: str, market_token: str, account_username: str
) -> dict[str, Any]:
    from app.mod_sdk.customer_delivery_seed import (
        install_customer_delivery_seed_package as operation,
    )

    return cast(
        "dict[str, Any]",
        await operation(
            request=request,
            mod_id=mod_id,
            industry_id=industry_id,
            market_token=market_token,
            account_username=account_username,
        ),
    )


async def install_industry_seed(industry_id: str) -> dict[str, Any]:
    from app.mod_sdk.industry_seed import install_industry_seed_with_fallback as operation

    return cast("dict[str, Any]", await operation(industry_id))


def is_desktop() -> bool:
    from app.desktop_runtime.desktop_runtime_paths import is_desktop_mode as operation

    return cast("bool", operation())


def latest_market_token(*, user_id: int | None = None) -> str:
    from app.fastapi_routes.market_account import latest_session_market_token as operation

    return cast("str", operation(user_id=user_id))


def list_posts(*, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    from app.application.ai_circle_service import list_posts as operation

    return cast("list[dict[str, Any]]", operation(user_id=user_id, limit=limit))


def roster_document() -> dict[str, Any]:
    from app.mod_sdk.duty_roster import load_duty_roster_document as operation

    return cast("dict[str, Any]", operation())


def fixed_contacts(surface: str) -> dict[str, Any]:
    from app.application.surface_contacts import mobile_fixed_contacts as operation

    return cast("dict[str, Any]", operation(surface))


async def process_cs_message(
    conversation_id: int, customer_user_id: int, message_id: int, body: str
) -> None:
    from app.application.enterprise_cs_automation import (
        process_enterprise_cs_customer_message as operation,
    )

    await operation(conversation_id, customer_user_id, message_id, body)


def register_relay(*, host: str, port: int) -> dict[str, Any]:
    from app.application.facades.mobile_relay_facade import register_desktop_relay as operation

    return cast("dict[str, Any]", operation(host=host, port=port))


async def resolve_market_token(session_id: str) -> str:
    from app.fastapi_routes.market_account import resolve_valid_market_access_token as operation

    return cast("str", await operation(session_id))


def request_session_id(request: Request) -> str:
    from app.infrastructure.auth.dependencies import session_id_from_request as operation

    return cast("str", operation(request))


def session_market_token(sid: str) -> str:
    from app.fastapi_routes.market_account import session_market_token as operation

    return cast("str", operation(sid))


def set_account_industry(username: str, industry_id: str) -> None:
    from app.application.account_registration import set_account_industry as operation

    operation(username, industry_id)


async def sync_circle() -> object:
    from app.application.employee_circle_sync import sync_modstore_reports as operation

    return await operation()


def toggle_like(*, post_id: int, user_id: int) -> bool:
    from app.application.ai_circle_service import toggle_like as operation

    return cast("bool", operation(post_id=post_id, user_id=user_id))


def now() -> datetime:
    from app.utils.time import utc_now_naive as operation

    return cast("datetime", operation())


def verify_jwt(token: str) -> dict[str, Any] | None:
    from app.security.mobile_jwt import verify_mobile_jwt as operation

    return cast("dict[str, Any] | None", operation(token))
