# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


async def send_market_reset_password_code(email: str) -> dict[str, _facade().Any]:
    """Request password-reset verification email from the configured market server."""
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        return {"success": False, "message": "请填写有效邮箱"}
    payload = await _facade()._proxy_json(
        "POST",
        "/api/auth/send-reset-password-code",
        json_body={"email": email_norm},
        return_error_payload=True,
    )
    if isinstance(payload, _facade().JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _facade()._error_message(raw, status_code) or "无法连接修茈市场发送验证码",
            "market_base_url": _facade()._market_base_url(),
        }
    msg = ""
    if isinstance(payload, dict):
        msg = str(payload.get("message") or "").strip()
    return {
        "success": True,
        "message": msg or "若该邮箱已注册，将收到验证码邮件",
        "market_base_url": _facade()._market_base_url(),
        "raw": payload,
    }


async def send_market_register_code(email: str) -> dict[str, _facade().Any]:
    """Request a registration code from the canonical market identity service."""
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        return {"success": False, "message": "请填写有效邮箱", "status_code": 400}
    payload = await _facade()._proxy_json(
        "POST",
        "/api/auth/send-register-code",
        json_body={"email": email_norm},
        return_error_payload=True,
    )
    if isinstance(payload, _facade().JSONResponse):
        return {"success": False, "message": "市场服务不可用", "status_code": 502}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _facade()._error_message(raw, status_code) or "发送验证码失败",
            "status_code": status_code,
        }
    message = str(payload.get("message") or "") if isinstance(payload, dict) else ""
    return {"success": True, "message": message or "验证码已发送"}


async def reset_market_password_with_code(
    email: str, code: str, new_password: str
) -> dict[str, _facade().Any]:
    """Reset password on market server using email verification code."""
    email_norm = (email or "").strip().lower()
    code_s = (code or "").strip()
    if not email_norm or "@" not in email_norm:
        return {"success": False, "message": "请填写有效邮箱"}
    if len(code_s) < 4:
        return {"success": False, "message": "请填写验证码"}
    if len(new_password or "") < 6:
        return {"success": False, "message": "新密码至少 6 个字符"}
    payload = await _facade()._proxy_json(
        "POST",
        "/api/auth/reset-password",
        json_body={"email": email_norm, "code": code_s, "new_password": new_password},
        return_error_payload=True,
    )
    if isinstance(payload, _facade().JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _facade()._error_message(raw, status_code) or "重置失败",
            "raw": raw,
        }
    if isinstance(payload, dict) and payload.get("success") is False:
        return {
            "success": False,
            "message": str(payload.get("message") or payload.get("detail") or "重置失败"),
            "raw": payload,
        }
    return {"success": True, "message": "密码已重置", "raw": payload}


async def register_market_user(
    username: str, password: str, email: str, verification_code: str = ""
) -> dict[str, _facade().Any]:
    """Register on the configured Xiuci market server. Returns success/message/token/raw."""
    register_body = {
        "username": username,
        "password": password,
        "email": email,
        "verification_code": (verification_code or "").strip(),
    }
    payload = await _facade()._proxy_json(
        "POST", "/api/auth/register", json_body=register_body, return_error_payload=True
    )
    if isinstance(payload, _facade().JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw_error = payload.get("payload")
        if status_code >= 400:
            return {
                "success": False,
                "message": _facade()._error_message(raw_error, status_code),
                "raw": raw_error,
            }
    normalized = await _facade()._normalize_market_auth_payload(payload)
    normalized["market_user_id"] = _facade()._market_user_id_from_auth_payload(payload)
    return normalized


@_facade().router.post("/register")
async def market_register(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """Register a Xiuci market account through the configured market server."""
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    email = str(body.get("email") or "").strip()
    verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
    if not username or not password:
        return _facade().JSONResponse(
            {"success": False, "message": "username、password 必填"}, status_code=400
        )
    result = await _facade().register_market_user(username, password, email, verification_code)
    if not result.get("success"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": result.get("message", "注册失败"),
                "data": result.get("raw"),
            },
            status_code=400,
        )
    token, _ = _facade().bind_market_auth_to_session(request, result)
    return {
        "success": True,
        "data": {
            "market_base_url": result.get("market_base_url"),
            "token": token,
            "refresh_token": result.get("refresh_token"),
            "account_state": result.get("account_state"),
            "next_action": result.get("next_action"),
            "desktop_access": bool(result.get("desktop_access")),
            "active_plan_id": result.get("active_plan_id"),
            "account_tier": result.get("account_tier"),
            "raw": result.get("raw"),
        },
    }


@_facade().router.post("/login")
async def market_login(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """Login to Xiuci market (username/password) and bind JWT to the current FHD session.

    Prefer ``POST /api/auth/login`` for the desktop app; this route remains for
    settings/tools that only need market credentials. Token-only bind: ``POST /account-sync``.
    """
    username = str(body.get("username") or body.get("email") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        return _facade().JSONResponse(
            {"success": False, "message": "username 与 password 必填"}, status_code=400
        )
    market_result = await _facade().login_market_with_password(username, password)
    if not market_result.get("success"):
        return _facade().JSONResponse(
            {"success": False, "message": market_result.get("message", "市场登录失败")},
            status_code=403,
        )
    token, refresh = _facade().bind_market_auth_to_session(request, market_result)
    return {
        "success": True,
        "data": {
            "market_base_url": _facade()._market_base_url(),
            "token": token,
            "refresh_token": refresh,
            "account_state": market_result.get("account_state"),
            "next_action": market_result.get("next_action"),
            "desktop_access": bool(market_result.get("desktop_access")),
            "active_plan_id": market_result.get("active_plan_id"),
            "account_tier": market_result.get("account_tier"),
            "raw": market_result.get("raw"),
        },
    }


def _is_local_market_base(url: str) -> bool:
    host = (url or "").strip().lower()
    return "127.0.0.1" in host or "localhost" in host


def _demo_market_login_payload(
    shim: dict[str, _facade().Any], *, market_base_url: str
) -> dict[str, _facade().Any]:
    raw_out = dict(shim.get("raw") or {})
    if not isinstance(raw_out.get("user"), dict):
        raw_out["user"] = {
            "id": int((shim.get("raw") or {}).get("user", {}).get("id") or 900001),
            "username": str((shim.get("raw") or {}).get("user", {}).get("username") or ""),
            "is_enterprise": True,
            "is_admin": False,
        }
    return {
        "success": True,
        "market_base_url": market_base_url,
        "token": str(shim.get("token") or "").strip(),
        "refresh_token": str(shim.get("refresh_token") or "").strip(),
        "is_enterprise": bool(shim.get("is_enterprise")),
        "is_market_admin": bool(shim.get("is_market_admin")),
        "raw": raw_out,
    }


async def _normalize_market_auth_payload(
    payload: _facade().Any, *, market_base: str | None = None
) -> dict[str, _facade().Any]:
    """Turn market login JSON into normalized token payload."""
    if isinstance(payload, _facade().JSONResponse):
        try:
            raw_body = _facade().json.loads(
                bytes(payload.body).decode("utf-8") if payload.body else "{}"
            )
        except _facade().RECOVERABLE_ERRORS:
            raw_body = {}
        status_code = int(payload.status_code or 502)
        message = (
            str(raw_body.get("message") or "").strip()
            or str(raw_body.get("detail") or "").strip()
            or _facade()._error_message(raw_body, status_code)
        )
        err = raw_body.get("error") if isinstance(raw_body.get("error"), dict) else {}
        code = str(err.get("code") or "").strip()
        if status_code >= 500 and (not code):
            code = "MARKET_AUTH_UNAVAILABLE"
        return {
            "success": False,
            "message": message,
            "status_code": status_code,
            "error_code": code
            or ("MARKET_AUTH_UNAVAILABLE" if status_code >= 500 else "MARKET_AUTH_FAILED"),
            "raw": raw_body,
            "market_base_url": market_base or _facade()._market_base_url(),
        }
    token = _facade()._token_from_auth_response(payload)
    refresh = _facade()._refresh_token_from_auth_response(payload)
    if not token:
        return {"success": False, "message": "市场登录成功但未返回 access_token", "raw": payload}
    me = await _facade()._proxy_json(
        "GET", "/api/auth/me", authorization=f"Bearer {token}", return_error_payload=True
    )
    is_enterprise, is_market_admin, user_blob = _facade()._market_identity_from_payloads(
        payload, me
    )
    lifecycle = _facade()._market_lifecycle_from_payloads(payload, me)
    _facade().logger.info(
        "market auth normalized base=%s success=True is_enterprise=%s is_market_admin=%s username=%s raw_keys=%s me_keys=%s",
        market_base or _facade()._market_base_url(),
        is_enterprise,
        is_market_admin,
        str(user_blob.get("username") or ""),
        sorted(payload.keys()) if isinstance(payload, dict) else [],
        sorted(me.keys()) if isinstance(me, dict) else [],
    )
    raw_out = dict(payload) if isinstance(payload, dict) else {}
    if user_blob and (not isinstance(raw_out.get("user"), dict)):
        raw_out["user"] = user_blob
    return {
        "success": True,
        "market_base_url": market_base or _facade()._market_base_url(),
        "token": token,
        "refresh_token": refresh,
        "is_enterprise": is_enterprise,
        "is_market_admin": is_market_admin,
        **lifecycle,
        "raw": raw_out,
    }
