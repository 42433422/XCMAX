# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.market_auth_api_part01_part01_part02 import RefreshTokenDTO


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


@_facade().router.post("/auth/refresh", summary="用 refresh_token 换取新的 access_token")
def api_refresh_token(body: RefreshTokenDTO):
    refresh_token = body.refresh_token
    if not refresh_token:
        raise _facade().HTTPException(400, "缺少刷新令牌")
    payload = _facade().decode_refresh_token(refresh_token)
    if not payload:
        raise _facade().HTTPException(401, "刷新令牌无效或已过期")
    user_id = int(payload["sub"])
    username = payload["username"]
    user = _facade().get_user_by_id(user_id)
    if not user:
        raise _facade().HTTPException(401, "用户不存在")
    new_access_token = _facade().create_access_token(
        user_id, username, is_admin=bool(user.is_admin)
    )
    new_refresh_token = _facade().create_refresh_token(user_id, username)
    return {
        "ok": True,
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        },
    }


class SendPhoneCodeDTO(_facade().BaseModel):
    phone: str = _facade().Field(..., min_length=5, max_length=32)


class LoginWithPhoneCodeDTO(_facade().BaseModel):
    phone: str = _facade().Field(..., min_length=5, max_length=32)
    code: str = _facade().Field(..., min_length=4, max_length=16)


@_facade().router.post("/auth/send-phone-code", summary="发送手机短信验证码")
def api_send_phone_code(body: SendPhoneCodeDTO, request: _facade().Request):
    """发送短信验证码登录。当前实现：以邮箱接口替代（若已配置 SMS_PROVIDER 则由运营对接）。
    前端 sendPhoneCode 消费此接口。未配置 SMS 服务时返回 503。
    """
    sms_provider = (_facade().os.environ.get("SMS_PROVIDER") or "").strip()
    if not sms_provider:
        raise _facade().HTTPException(503, "短信服务未配置，请使用邮箱验证码登录")
    raise _facade().HTTPException(501, "短信验证码功能待接入，请联系管理员")


@_facade().router.post("/auth/login-with-phone-code", summary="手机验证码登录")
def api_login_with_phone_code(body: LoginWithPhoneCodeDTO):
    """手机验证码登录（与 send-phone-code 配套）。未配置 SMS 时返回 503。"""
    sms_provider = (_facade().os.environ.get("SMS_PROVIDER") or "").strip()
    if not sms_provider:
        raise _facade().HTTPException(503, "短信服务未配置，请使用邮箱验证码登录")
    raise _facade().HTTPException(501, "短信验证码功能待接入，请联系管理员")


class VerifyAdminDigestCodeDTO(_facade().BaseModel):
    code: str = _facade().Field(..., min_length=1, max_length=32)


def normalize_admin_digest_code(raw: str) -> str:
    """与 :mod:`digest_identity` 一致，保留别名供其它模块引用。"""
    return _facade().normalize_digest_identity_code(raw)


@_facade().router.post(
    "/auth/verify-admin-digest-code",
    summary="校验每日摘要邮件中的 6 位身份码以解锁管理端 UI",
    tags=["auth", "admin"],
)
def api_verify_admin_digest_code(
    body: VerifyAdminDigestCodeDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """已是管理员 JWT 的账号，凭当日摘要邮件「身份校验码」解锁前端管理端 Tab。

    仅做只读校验：匹配 sha256 + 未过期；**不会** 设置 ``used_at``，避免影响邮件回信侧
    的 ``digest_identity`` 一次性消费逻辑。

    校验实现见 :func:`modstore_server.digest_identity.verify_digest_identity`（与
    ``GET /api/xcmax/admin/digest-identity`` 同源）。
    """
    code = _facade().normalize_digest_identity_code(body.code or "")
    if len(code) != 6 or any((c not in "0123456789ABCDEF" for c in code)):
        raise _facade().HTTPException(400, "身份码格式错误，应为 6 位十六进制")
    sf = _facade().get_session_factory()
    with sf() as session:
        expires_iso = _facade().verify_digest_identity(session, code)
        if expires_iso:
            return {"ok": True, "expires_at": expires_iso}
    upstream_expires = _facade().call_upstream_digest_verify(code)
    if upstream_expires:
        return {"ok": True, "expires_at": upstream_expires}
    raise _facade().HTTPException(
        400,
        "身份码无效或已过期。若需公网市场校验自建库签发的码，请在公网实例配置 MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL，自建端开启 MODSTORE_DIGEST_PEER_ENABLE_INBOUND=1，且两端使用相同 MODSTORE_DIGEST_PEER_SERVICE_TOKEN（详见 .env.example）。",
    )


class AccountDeleteDTO(_facade().BaseModel):
    password: str = _facade().Field(..., min_length=6, max_length=128)


@_facade().router.post("/auth/account/delete", summary="注销当前账号（软删除）")
def api_account_delete(
    body: AccountDeleteDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            return {"ok": True, "message": "账号已注销"}
        if not _facade().verify_password(body.password, row.password_hash):
            raise _facade().HTTPException(400, "密码不正确")
        row.deleted_at = _facade().datetime.now(_facade().timezone.utc)
        row.password_hash = _facade().hash_password(_facade().os.urandom(32).hex())
        session.commit()
    return {"ok": True, "message": "账号已注销"}


@_facade().router.get("/auth/export", summary="导出当前账号数据（JSON）")
def api_account_export(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": getattr(user, "phone", None) or "",
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
            "experience": int(getattr(user, "experience", 0) or 0),
            "created_at": user.created_at.isoformat() if user.created_at else "",
        },
        "exported_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
    }


@_facade().router.get(
    "/admin/status", summary="管理端概要统计（需管理员 JWT）", tags=["auth", "admin"]
)
def api_admin_status(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total_items = session.query(_facade().CatalogItem).count()
        total_users = session.query(_facade().User).count()
        return {
            "ok": True,
            "is_admin": True,
            "total_catalog_items": total_items,
            "total_users": total_users,
        }
