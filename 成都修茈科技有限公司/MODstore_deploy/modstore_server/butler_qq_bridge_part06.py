# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


def invalidate_bot_ctx_cache() -> None:
    """admin 改完账号 / 轮换密钥后，让下一次 _get_bot_ctx 重新查 DB。"""
    _facade()._bot_ctx_cache.clear()


async def _get_bot_ctx(app_id: str) -> _facade().Optional[_facade()._BotContext]:
    """按 app_id 从账号池找对应员工凭证，缓存 BotContext。

    匹配优先级：
    1) ``external_id == app_id``（DB 用 QQ AppID 当对外标识时最直接）
    2) 遍历所有 active 的 QQ 账号，比对密钥文件里的 ``secret.app_id``——
       支持运维把 ``external_id`` 写成 QQ 号、邮箱等"业务标识"的场景。
    """
    if app_id in _facade()._bot_ctx_cache:
        return _facade()._bot_ctx_cache[app_id]
    async with _facade()._bot_ctx_lock:
        if app_id in _facade()._bot_ctx_cache:
            return _facade()._bot_ctx_cache[app_id]
        try:
            from modstore_server.ai_employee_account_secrets import read_secret
            from modstore_server.models import get_session_factory
            from modstore_server.models_ai_accounts import AIEmployeeAccount

            sf = get_session_factory()
            row = None
            secret: _facade().Dict[str, _facade().Any] = {}
            with sf() as session:
                row = (
                    session.query(AIEmployeeAccount)
                    .filter(
                        AIEmployeeAccount.platform == "qq",
                        AIEmployeeAccount.external_id == app_id,
                        AIEmployeeAccount.status == "active",
                    )
                    .first()
                )
                if row:
                    secret = read_secret(platform="qq", account_id=int(row.id)) or {}
                if not row or not secret:
                    rows = (
                        session.query(AIEmployeeAccount)
                        .filter(
                            AIEmployeeAccount.platform == "qq",
                            AIEmployeeAccount.status == "active",
                        )
                        .all()
                    )
                    for r in rows:
                        sec = read_secret(platform="qq", account_id=int(r.id)) or {}
                        if str(sec.get("app_id") or "").strip() == app_id:
                            row = r
                            secret = sec
                            break
            if row and secret:
                ctx = _facade()._BotContext(
                    employee_id=row.employee_id,
                    app_id=str(secret.get("app_id") or app_id),
                    app_secret=str(secret.get("app_secret") or ""),
                    sandbox=bool(row.sandbox),
                    bot_token=str(secret.get("bot_token") or ""),
                )
                _facade()._bot_ctx_cache[app_id] = ctx
                return ctx
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.debug("_get_bot_ctx 失败 app_id=%s: %s", app_id, exc)
        for webhook_key, spec in _facade()._SPECIFIC_WEBHOOKS.items():
            if spec.get("app_id") == app_id:
                secret = _facade()._specific_app_secret(webhook_key)
                eid = spec.get("employee_id", "")
                if secret and eid:
                    ctx = _facade()._BotContext(
                        employee_id=eid,
                        app_id=app_id,
                        app_secret=secret,
                        sandbox=False,
                        bot_token=_facade()._specific_bot_token(webhook_key),
                    )
                    _facade()._bot_ctx_cache[app_id] = ctx
                    return ctx
        return None


def _specific_ctx_for_employee(
    employee_id: str,
) -> _facade().Optional[_facade()._BotContext]:
    """从 ``_SPECIFIC_WEBHOOKS`` 静态表里查一份兜底 ctx；DB 都没建好时也能跑。"""
    eid = (employee_id or "").strip()
    if not eid:
        return None
    for webhook_key, spec in _facade()._SPECIFIC_WEBHOOKS.items():
        if spec.get("employee_id") == eid:
            secret = _facade()._specific_app_secret(webhook_key)
            app_id = spec.get("app_id", "")
            if app_id and secret:
                return _facade()._BotContext(
                    employee_id=eid,
                    app_id=app_id,
                    app_secret=secret,
                    sandbox=False,
                    bot_token=_facade()._specific_bot_token(webhook_key),
                )
    return None


async def _get_bot_ctx_by_employee(
    employee_id: str,
) -> _facade().Optional[_facade()._BotContext]:
    """按 employee_id 找对应 QQ 机器人 ctx——给"按员工"的通用 webhook 使用。

    DB 上同一员工可能挂多个 QQ 账号，取最新一条 active；查不到再尝试
    ``_SPECIFIC_WEBHOOKS`` 静态兜底（覆盖 ``task-router-officer`` /
    ``employee-interview-assistant`` 这两位老员工）；都没有返回 None。
    """
    eid = (employee_id or "").strip()
    if not eid:
        return None
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(eid, "qq")
        if rec:
            secret = rec.get("secret") or {}
            app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
            app_secret = str(secret.get("app_secret") or "").strip()
            if app_id and app_secret:
                if app_id in _facade()._bot_ctx_cache:
                    return _facade()._bot_ctx_cache[app_id]
                ctx = _facade()._BotContext(
                    employee_id=eid,
                    app_id=app_id,
                    app_secret=app_secret,
                    sandbox=bool(rec.get("sandbox")),
                    bot_token=str(secret.get("bot_token") or ""),
                )
                _facade()._bot_ctx_cache[app_id] = ctx
                return ctx
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("_get_bot_ctx_by_employee 失败 employee_id=%s: %s", employee_id, exc)
    static_ctx = _facade()._specific_ctx_for_employee(eid)
    if static_ctx is not None:
        if static_ctx.app_id not in _facade()._bot_ctx_cache:
            _facade()._bot_ctx_cache[static_ctx.app_id] = static_ctx
        return static_ctx
    return None
