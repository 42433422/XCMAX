"""Revalidate durable Agent Mod scope against a host session, never a token cache."""

import json
from contextlib import contextmanager
from typing import Any

from app.request_active_mod_ctx import (
    normalize_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


class AgentModAuthorizationError(ValueError):
    pass


def _check_row(row: Any, *, user_id: str, mod_id: str) -> None:
    from app.mod_sdk.industry_seed import open_industry_seed_mod_ids
    from app.mod_sdk.product_skus import bundled_mod_ids_for_sku, resolve_product_sku
    from app.utils.time import utc_now_naive

    if row is None or str(row.user_id) != user_id or row.expires_at <= utc_now_naive():
        raise AgentModAuthorizationError("任务绑定的登录会话已失效")
    if row.user is None or not row.user.is_active:
        raise AgentModAuthorizationError("任务所属账号已停用")
    ids = json.loads(row.entitled_mod_ids_json or "[]")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        raise AgentModAuthorizationError("任务 Mod 权益记录无效")
    public_ids = set(bundled_mod_ids_for_sku(resolve_product_sku()))
    public_ids.update(open_industry_seed_mod_ids())
    if mod_id not in set(ids) | public_ids:
        raise AgentModAuthorizationError("任务所属账号未开通该 Mod")


def bind_agent_mod_scope(*, session_id: str, user_id: str, mod_id: str) -> dict[str, Any]:
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    normalized = normalize_active_mod_id(mod_id)
    if not normalized or normalized != mod_id or not session_id:
        raise AgentModAuthorizationError("Mod 任务需要有效的登录会话")
    with HostSessionLocal() as db:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        _check_row(row, user_id=user_id, mod_id=normalized)
        return {"session_row_id": row.id, "user_id": user_id, "mod_id": normalized}


@contextmanager
def agent_mod_execution_scope(binding: dict[str, Any] | None):
    if not binding:
        yield
        return
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    if not isinstance(binding, dict):
        raise AgentModAuthorizationError("任务 Mod 授权上下文无效")
    row_id = binding.get("session_row_id")
    mod_id = binding.get("mod_id")
    user_id = binding.get("user_id")
    if (
        type(row_id) is not int
        or row_id <= 0
        or not isinstance(user_id, str)
        or not isinstance(mod_id, str)
        or not mod_id
        or normalize_active_mod_id(mod_id) != mod_id
    ):
        raise AgentModAuthorizationError("任务 Mod 授权上下文无效")
    with HostSessionLocal() as db:
        _check_row(db.get(UserSession, row_id), user_id=user_id, mod_id=mod_id)
    token = set_request_active_mod_id(mod_id)
    try:
        yield
    finally:
        reset_request_active_mod_id(token)
