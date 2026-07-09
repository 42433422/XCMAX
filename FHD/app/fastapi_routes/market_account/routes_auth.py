"""Market auth/session HTTP routes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.market_account._patch as _p
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/session-handoff")
async def market_session_handoff(request: Request):
    """Return the Xiuci market JWT bound to the current FHD session.

    Login stores this in-memory via ``_p.save_session_market_token``; the SPA needs it in
    ``localStorage`` to append ``xcagi_mt=`` on cross-origin links (cookies do not carry).
    """
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        if user is None:
            tok = _p._normalize_bearer_token(_p.latest_session_market_token())
            if tok:
                return {
                    "success": True,
                    "data": {
                        "market_access_token": tok,
                        "market_base_url": _p._market_base_url(),
                    },
                }
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "当前会话未绑定修茈市场账号。请使用与本软件相同的用户名与密码重新登录，"
                        "或在设置中粘贴修茈 Authorization 完成同步。"
                    ),
                },
                status_code=404,
            )
        sid = _p.session_id_from_request(request)
        tok = await _p.resolve_valid_market_access_token(sid)
        if not tok:
            tok = _p._normalize_bearer_token(
                _p.latest_session_market_token(user_id=getattr(user, "id", None))
            )
            if tok:
                tok = await _p.resolve_valid_market_access_token(sid)
        if not tok:
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "当前会话未绑定修茈市场账号。请使用与本软件相同的用户名与密码重新登录，"
                        "或在设置中粘贴修茈 Authorization 完成同步。"
                    ),
                },
                status_code=404,
            )
        _ = user  # validated logged-in user
        refresh_out = _p.session_market_refresh_token(sid) or _p.latest_session_market_refresh_token()
        data: dict[str, Any] = {
            "market_access_token": tok,
            "market_base_url": _p._market_base_url(),
        }
        if refresh_out:
            data["market_refresh_token"] = refresh_out
        try:
            if sid:
                from app.enterprise.mod_entitlements import sync_entitlements_for_session

                await sync_entitlements_for_session(sid)
        except RECOVERABLE_ERRORS:
            logger.exception("enterprise entitlements refresh on session-handoff failed")
        return {"success": True, "data": data}
    except RECOVERABLE_ERRORS:
        logger.exception("market_session_handoff failed")
        sid = _p.session_id_from_request(request)
        fallback_tok = _p._normalize_bearer_token(
            _p.session_market_token(sid) or _p.latest_session_market_token()
        )
        if fallback_tok:
            return {
                "success": True,
                "data": {
                    "market_access_token": fallback_tok,
                    "market_base_url": _p._market_base_url(),
                },
            }
        return JSONResponse(
            {
                "success": False,
                "message": (
                    "修茈市场会话交接暂时不可用，请稍后重试或检查 XCAGI_MARKET_BASE_URL 与市场服务状态。"
                ),
                "data": {"market_base_url": _p._market_base_url()},
            },
            status_code=502,
        )

@router.get("/membership-plans")
async def market_membership_plans():
    """会员套餐列表（代理市场公开接口 ``GET /api/payment/plans``）。

    供 ModelPaymentView 读取，替代前端硬编码；市场不可达时返回空列表，前端用本地 FALLBACK。
    """
    data = await _p._proxy_json("GET", "/api/payment/plans", return_error_payload=True)
    if isinstance(data, dict) and not data.get("__proxy_error__"):
        plans = data.get("plans")
        return {"success": True, "data": {"plans": plans if isinstance(plans, list) else []}}
    return {"success": True, "data": {"plans": []}}

@router.post("/register")
async def market_register(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """Register a Xiuci market account through the configured market server."""
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    email = str(body.get("email") or "").strip()
    verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
    if not username or not password or not email:
        return JSONResponse(
            {"success": False, "message": "username、password、email 必填"}, status_code=400
        )
    result = await _p.register_market_user(username, password, email, verification_code)
    if not result.get("success"):
        return JSONResponse(
            {
                "success": False,
                "message": result.get("message", "注册失败"),
                "data": result.get("raw"),
            },
            status_code=400,
        )
    token, _ = _p.bind_market_auth_to_session(request, result)
    return {
        "success": True,
        "data": {
            "market_base_url": result.get("market_base_url"),
            "token": token,
            "raw": result.get("raw"),
        },
    }

@router.post("/login")
async def market_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """Login to Xiuci market (username/password) and bind JWT to the current FHD session.

    Prefer ``POST /api/auth/login`` for the desktop app; this route remains for
    settings/tools that only need market credentials. Token-only bind: ``POST /account-sync``.
    """
    username = str(body.get("username") or body.get("email") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        return JSONResponse(
            {"success": False, "message": "username 与 password 必填"}, status_code=400
        )
    market_result = await _p.login_market_with_password(username, password)
    if not market_result.get("success"):
        return JSONResponse(
            {"success": False, "message": market_result.get("message", "市场登录失败")},
            status_code=403,
        )
    token, refresh = _p.bind_market_auth_to_session(request, market_result)
    return {
        "success": True,
        "data": {
            "market_base_url": _p._market_base_url(),
            "token": token,
            "raw": market_result.get("raw"),
        },
    }

@router.post("/send-phone-code")
async def market_send_phone_code(body: dict[str, Any] = Body(default_factory=dict)):
    phone = str(body.get("phone") or "").strip()
    if not phone:
        return JSONResponse({"success": False, "message": "请填写手机号"}, status_code=400)
    result = await _p.send_market_phone_code(phone)
    if not result.get("success"):
        status = int(result.get("status_code") or 502)
        return JSONResponse(result, status_code=status if status >= 400 else 502)
    return {"success": True, "message": result.get("message") or "验证码已发送"}

@router.post("/login-with-phone-code")
async def market_login_with_phone_code_route(body: dict[str, Any] = Body(default_factory=dict)):
    phone = str(body.get("phone") or "").strip()
    code = str(body.get("code") or "").strip()
    if not phone or not code:
        return JSONResponse({"success": False, "message": "请填写手机号和验证码"}, status_code=400)
    result = await _p.login_market_with_phone_code(phone, code)
    if not result.get("success"):
        status = int(result.get("status_code") or 401)
        return JSONResponse(
            {
                "success": False,
                "message": result.get("message"),
                "error": {
                    "code": result.get("error_code") or "MARKET_AUTH_FAILED",
                    "message": result.get("message"),
                },
            },
            status_code=status if status >= 400 else 401,
        )
    return {
        "success": True,
        "data": {
            "token": result.get("token"),
            "refresh_token": result.get("refresh_token"),
            "market_base_url": result.get("market_base_url"),
        },
    }

@router.get("/status")
async def market_status():
    """Check whether the local backend can reach the configured Xiuci market server."""
    payload = await _p._proxy_json("GET", "/api/health", return_error_payload=True)
    if isinstance(payload, JSONResponse):
        return payload
    reachable = not (isinstance(payload, dict) and payload.get("__proxy_error__"))
    return {
        "success": reachable,
        "data": {
            "market_base_url": _p._market_base_url(),
            "reachable": reachable,
            "raw": (
                payload.get("payload")
                if isinstance(payload, dict) and payload.get("__proxy_error__")
                else payload
            ),
        },
    }

@router.post("/dev-create-account")
async def market_dev_create_account(body: dict[str, Any] = Body(default_factory=dict)):
    """Create a market account via server-side open API and verify login/overview connectivity."""
    username = str(body.get("username") or f"xcagi_{uuid.uuid4().hex[:10]}").strip()
    password = str(body.get("password") or uuid.uuid4().hex[:12])
    email = str(body.get("email") or f"{username}@xcagi.local").strip()
    if len(password) < 6:
        return JSONResponse({"success": False, "message": "password 至少 6 位"}, status_code=400)

    payload = await _p._register_without_verification(username, password, email)
    if isinstance(payload, JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw_error = payload.get("payload")
        if status_code == 409 or "存在" in _p._error_message(raw_error, status_code):
            payload = await _p._proxy_json(
                "POST", "/api/auth/login", json_body={"username": username, "password": password}
            )
        else:
            return JSONResponse(
                {
                    "success": False,
                    "message": _p._error_message(raw_error, status_code),
                    "data": raw_error,
                },
                status_code=status_code,
            )
    token = _p._token_from_auth_response(payload)
    if not token:
        return JSONResponse(
            {"success": False, "message": "账号创建成功但未返回 token", "data": payload},
            status_code=502,
        )
    overview = await _p._proxy_json(
        "GET", "/api/account/bootstrap", authorization=token, return_error_payload=True
    )
    return {
        "success": True,
        "data": {
            "market_base_url": _p._market_base_url(),
            "username": username,
            "email": email,
            "password": password,
            "token": token,
            "overview_ok": not (isinstance(overview, dict) and overview.get("__proxy_error__")),
            "overview": (
                overview.get("payload")
                if isinstance(overview, dict) and overview.get("__proxy_error__")
                else overview
            ),
        },
    }
