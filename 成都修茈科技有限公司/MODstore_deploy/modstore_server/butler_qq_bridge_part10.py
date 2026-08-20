# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


class _PushDTO(_facade().BaseModel):
    kind: _facade().MsgKind
    target_id: str
    content: str = _facade().Field(..., min_length=1, max_length=2000)
    msg_id: str = ""
    msg_seq: _facade().Optional[int] = None


def _check_admin(request: _facade().Request) -> None:
    expected = _facade()._env("MODSTORE_ADMIN_RECHARGE_TOKEN")
    if not expected:
        raise _facade().HTTPException(503, "MODSTORE_ADMIN_RECHARGE_TOKEN 未配置，拒绝主动推送")
    got = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if got != expected:
        raise _facade().HTTPException(403, "管理员令牌不匹配")


@_facade().router.get("/status")
async def qq_status() -> _facade().Dict[str, _facade().Any]:
    own_provider, own_model, own_key, _own_base = _facade()._own_llm()
    has_own_brain = bool(own_provider and own_key)
    creds = _facade()._resolve_creds()
    employees: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for webhook_key, spec in _facade()._SPECIFIC_WEBHOOKS.items():
        eid = spec.get("employee_id", "")
        aid = spec.get("app_id", "")
        secret_present = bool(_facade()._specific_app_secret(webhook_key))
        bot_tok_present = bool(_facade()._specific_bot_token(webhook_key))
        employees.append(
            {
                "employee_id": eid,
                "app_id": aid,
                "webhook_key": webhook_key,
                "webhook_path": f"/api/agent/butler/qq/{webhook_key}/webhook",
                "by_employee_path": f"/api/agent/butler/qq/by-employee/{eid}/webhook",
                "app_secret_env": spec.get("app_secret_env", ""),
                "bot_token_env": spec.get("bot_token_env", ""),
                "app_secret_present": secret_present,
                "bot_token_present": bot_tok_present,
                "uses_executor": True,
            }
        )
    return {
        "configured": _facade().is_configured(),
        "credential_source": _facade()._qq_credential_source(),
        "account_id": creds.get("account_id"),
        "sandbox": _facade()._qq_sandbox(),
        "api_base": _facade()._qq_api_base(),
        "app_id": _facade()._qq_app_id() or None,
        "has_own_brain": has_own_brain,
        "own_brain_provider": own_provider or None,
        "own_brain_model": own_model or None,
        "bridge_user_id": _facade()._bridge_user_id() or None,
        "has_cached_token": bool(_facade()._token_state.token),
        "token_expires_in": (
            max(int(_facade()._token_state.expires_at - _facade().time.time()), 0)
            if _facade()._token_state.token
            else 0
        ),
        "first_class_employees": employees,
        "butler_employee_id": _facade()._BUTLER_EMPLOYEE_ID,
    }


@_facade().router.get("/webhook")
async def qq_webhook_probe() -> _facade().JSONResponse:
    """QQ platform GET probe for callback URL; real events use POST."""
    return _facade().JSONResponse({"ok": True})
