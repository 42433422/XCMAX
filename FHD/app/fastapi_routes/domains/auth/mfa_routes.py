"""Auth MFA HTTP routes (extracted for source-governance)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.http.error_codes import INVALID_INPUT, UNAUTHORIZED, error_envelope
from app.infrastructure.auth.dependencies import resolve_session_user

router = APIRouter(tags=["auth"])

@router.post("/api/auth/mfa/setup")
def auth_mfa_setup(request: Request):
    """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    from app.application.account_security import generate_totp_secret, provisioning_uri
    from app.db.models.user import User
    from app.db.session import get_db

    secret = generate_totp_secret()
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
        u.totp_secret = secret
        db.commit()
        username = u.username
    return {
        "success": True,
        "data": {"secret": secret, "otpauth_uri": provisioning_uri(secret, username)},
    }


@router.post("/api/auth/mfa/enable")
def auth_mfa_enable(request: Request, body: dict = Body(default_factory=dict)):
    """校验 TOTP 后开启 MFA。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None or not (u.totp_secret or ""):
            return JSONResponse(
                error_envelope(INVALID_INPUT, "请先调用 /api/auth/mfa/setup 生成密钥"),
                status_code=400,
            )
        if not verify_totp(u.totp_secret, code):
            return JSONResponse(error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400)
        u.mfa_enabled = True
        db.commit()
    return {"success": True, "message": "MFA 已开启"}


@router.post("/api/auth/mfa/disable")
def auth_mfa_disable(request: Request, body: dict = Body(default_factory=dict)):
    """关闭 MFA（已开启时需校验当前 TOTP）。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
        if u.mfa_enabled and not verify_totp(u.totp_secret or "", code):
            return JSONResponse(error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400)
        u.mfa_enabled = False
        u.totp_secret = None
        db.commit()
    return {"success": True, "message": "MFA 已关闭"}

