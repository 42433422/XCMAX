"""Capture and revalidate an account-owned Mod scope without storing session secrets."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    normalize_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


class TaskModScopeError(ValueError):
    pass


def _check(session, user, mod_id: str, owner: str, tenant: str) -> None:
    if session is None or user is None or not user.is_active:
        raise TaskModScopeError("模块任务的账号或会话已失效")
    if (
        str(session.user_id) != owner
        or str(user.id) != owner
        or str(user.tenant_id or "") != tenant
    ):
        raise TaskModScopeError("模块任务账号或租户不匹配")
    expiry = session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry <= datetime.now(UTC):
        raise TaskModScopeError("模块任务会话已过期，请登录后重新确认")
    from app.mod_sdk.product_skus import bundled_mod_ids_for_sku

    sku: Literal["enterprise", "personal"] = (
        "enterprise" if user.tier in {"enterprise", "admin"} else "personal"
    )
    if mod_id in set(bundled_mod_ids_for_sku(sku)):
        return
    from app.mod_sdk.industry_mod_aliases import canonical_mod_id, is_retired_runtime_mod_id
    from app.mod_sdk.industry_seed import open_industry_seed_mod_ids

    if is_retired_runtime_mod_id(mod_id):
        raise TaskModScopeError("模块已退役")
    if sku == "enterprise" and mod_id in set(open_industry_seed_mod_ids()):
        return
    ids = json.loads(session.entitled_mod_ids_json or "[]")
    if not isinstance(ids, list):
        raise TaskModScopeError("模块权益记录无效")
    entitled = {canonical_mod_id(item) for item in ids if isinstance(item, str)}
    if canonical_mod_id(mod_id) not in entitled:
        raise TaskModScopeError("当前账号没有该模块权益")


def capture_task_mod_scope(
    owner: str, tenant: str, *, mod_id: str | None = None
) -> dict[str, Any] | None:
    selected = (
        normalize_active_mod_id(mod_id) if mod_id is not None else get_request_active_mod_id()
    )
    if not selected:
        return None
    from app.db import HostSessionLocal
    from app.db.models.user import Session, User
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.infrastructure.request_context import get_current_request

    request = get_current_request()
    if request is None:
        raise TaskModScopeError("捕获模块任务需要已登录请求")
    sid = session_id_from_request(request)
    with HostSessionLocal() as db:
        session = db.query(Session).filter_by(session_id=sid).one_or_none() if sid else None
        user = db.get(User, session.user_id) if session else None
        _check(session, user, selected, owner, tenant)
        if session is None:
            raise TaskModScopeError("模块任务会话无效")
        return {
            "mod_id": selected,
            "session_record_id": session.id,
            "owner_id": owner,
            "tenant_id": tenant,
        }


def validate_task_mod_scope(scope: Any, owner: str, tenant: str) -> str:
    if not isinstance(scope, dict):
        raise TaskModScopeError("模块任务作用域无效")
    mod_id = normalize_active_mod_id(scope.get("mod_id"))
    record_id = scope.get("session_record_id")
    if not mod_id or type(record_id) is not int or record_id <= 0:
        raise TaskModScopeError("模块任务作用域无效")
    if scope.get("owner_id") != owner or scope.get("tenant_id") != tenant:
        raise TaskModScopeError("模块任务作用域不属于当前任务")
    from app.db import HostSessionLocal
    from app.db.models.user import Session, User

    with HostSessionLocal() as db:
        session = db.get(Session, record_id)
        user = db.get(User, session.user_id) if session else None
        _check(session, user, mod_id, owner, tenant)
    return mod_id


@contextmanager
def task_mod_execution_scope(context: dict[str, Any]) -> Iterator[None]:
    if "mod_scope" not in context:
        yield
        return
    scope = context.get("mod_scope")
    mod_id = (
        ""
        if scope is None
        else validate_task_mod_scope(
            scope, str(context.get("user_id") or ""), str(context.get("tenant_id") or "")
        )
    )
    token = set_request_active_mod_id(mod_id)
    try:
        yield
    finally:
        reset_request_active_mod_id(token)
