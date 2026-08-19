# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


def _enterprise_assignable_mod_ids() -> frozenset[str]:
    return _facade().enterprise_assignable_mod_ids()


def _assert_enterprise_assignable_mod_id(mod_id: str) -> str:
    try:
        return _facade().assert_enterprise_assignable_mod_id(mod_id)
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc


def _user_mod_ids_map(user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    from modstore_server.models_catalog import UserMod

    sf = _facade().get_session_factory()
    out: dict[int, list[str]] = {int(uid): [] for uid in user_ids}
    with sf() as session:
        rows = (
            session.query(UserMod.user_id, UserMod.mod_id)
            .filter(UserMod.user_id.in_(user_ids))
            .all()
        )
    for uid, mid in rows:
        key = int(uid)
        if mid and mid not in out.get(key, []):
            out.setdefault(key, []).append(str(mid))
    for uid in out:
        out[uid] = sorted(out[uid])
    return out


def _get_optional_user(
    authorization: _facade().Optional[str] = _facade().Header(None),
) -> _facade().Optional[_facade().User]:
    """可选登录依赖：Authorization 头存在且有效则返回 User，否则返回 None。
    使用 Depends(lambda) 无法让 FastAPI 注入 Header，必须用正式依赖函数。
    """
    if not authorization:
        return None
    try:
        return _facade()._get_current_user(authorization)
    except _facade().HTTPException:
        return None


class RegisterDTO(_facade().BaseModel):
    username: str = _facade().Field(..., min_length=2, max_length=64)
    password: str = _facade().Field(..., min_length=6)
    email: str = _facade().Field(default="", max_length=128, description="选填；填写时必须验证")
    verification_code: str = _facade().Field(default="", max_length=16, description="邮箱验证码")


class LoginDTO(_facade().BaseModel):
    username: str
    password: str


class SendCodeDTO(_facade().BaseModel):
    email: str


class LoginWithCodeDTO(_facade().BaseModel):
    email: str
    code: str


class RefreshTokenDTO(_facade().BaseModel):
    refresh_token: str


class ResetPasswordDTO(_facade().BaseModel):
    email: str
    code: str = _facade().Field(..., min_length=4, max_length=16)
    new_password: str = _facade().Field(..., min_length=6, max_length=128)


class AdminResetUserPasswordDTO(_facade().BaseModel):
    """线下运维：凭 MODSTORE_ADMIN_RECHARGE_TOKEN 重置指定用户密码（无邮件场景）。"""

    username: str = _facade().Field(..., min_length=1, max_length=64)
    new_password: str = _facade().Field(..., min_length=6, max_length=128)


class RechargeDTO(_facade().BaseModel):
    amount: float = _facade().Field(..., gt=0)
    description: str = ""
    recharge_token: str = ""


class AdminSelfCreditDTO(_facade().BaseModel):
    """管理员为本人钱包加款（无共享 Token）；金额上限见环境变量。"""

    amount: float = _facade().Field(..., gt=0)
    description: str = ""


class AiWalletPreauthorizeDTO(_facade().BaseModel):
    amount: float = _facade().Field(..., gt=0)
    provider: str = ""
    model: str = ""
    request_id: str = ""
    idempotency_key: str = _facade().Field(..., min_length=1, max_length=128)


class AiWalletSettleDTO(_facade().BaseModel):
    hold_no: str = _facade().Field(..., min_length=1, max_length=64)
    actual_amount: float = _facade().Field(..., ge=0)
    idempotency_key: str = _facade().Field(..., min_length=1, max_length=128)


class AiWalletReleaseDTO(_facade().BaseModel):
    hold_no: str = _facade().Field(..., min_length=1, max_length=64)
    reason: str = ""
    idempotency_key: str = _facade().Field(..., min_length=1, max_length=128)


class AiWalletRefundDTO(_facade().BaseModel):
    hold_no: str = _facade().Field(..., min_length=1, max_length=64)
    refund_amount: float = _facade().Field(..., gt=0)
    reason: str = ""
    idempotency_key: str = _facade().Field(..., min_length=1, max_length=128)


class BuyDTO(_facade().BaseModel):
    pass


class UploadCatalogDTO(_facade().BaseModel):
    pkg_id: str = _facade().Field(..., min_length=1, max_length=128)
    version: str = _facade().Field(..., min_length=1, max_length=32)
    name: str = _facade().Field(..., min_length=1, max_length=256)
    description: str = ""
    price: float = _facade().Field(..., ge=0)
    artifact: str = "mod"


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _delete_unused_verification_code(email: str, code: str) -> None:
    """发信失败时删除未使用的一条验证码，避免用户拿到无效码。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        session.query(_facade().VerificationCode).filter(
            _facade().VerificationCode.email == email,
            _facade().VerificationCode.code == code,
            _facade().VerificationCode.used.is_(False),
        ).delete(synchronize_session=False)
        session.commit()


def _background_send_verification_email(email: str, code: str, purpose: str) -> None:
    import logging

    try:
        _facade().send_verification_email(email, code, purpose)
    except Exception:
        logging.exception(
            "Background verification email failed email=%s purpose=%s", email, purpose
        )
        try:
            _facade()._delete_unused_verification_code(email, code)
        except Exception:
            logging.exception("Failed to remove verification code after email failure")


def _verify_and_consume_verification_code(email: str, code: str) -> None:
    """校验并作废一条未过期的邮箱验证码（email 须已小写归一化）。"""
    code = (code or "").strip()
    if not code:
        raise _facade().HTTPException(400, "请填写验证码")
    sf = _facade().get_session_factory()
    with sf() as session:
        vc = (
            session.query(_facade().VerificationCode)
            .filter(
                _facade().VerificationCode.email == email,
                _facade().VerificationCode.code == code,
                _facade().VerificationCode.used.is_(False),
                _facade().VerificationCode.expires_at
                > _facade().datetime.now(_facade().timezone.utc),
            )
            .order_by(_facade().VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise _facade().HTTPException(401, "验证码无效或已过期")
        vc.used = True
        session.commit()


@_facade().router.post("/auth/register")
def api_register(body: RegisterDTO):
    (email_norm, vcode) = (
        _facade()._normalize_email(body.email),
        (body.verification_code or "").strip(),
    )
    if email_norm and ("@" not in email_norm or not vcode):
        raise _facade().HTTPException(400, "填写邮箱后，请填写有效邮箱并获取邮箱验证码")
    if email_norm:
        _facade()._verify_and_consume_verification_code(email_norm, vcode)
    elif vcode:
        raise _facade().HTTPException(400, "填写验证码前请先填写邮箱")
    try:
        user = _facade().register_user(body.username, body.password, email_norm)
    except ValueError as e:
        raise _facade().HTTPException(409, str(e))
    access_token = _facade().create_access_token(
        user.id, user.username, is_admin=bool(user.is_admin)
    )
    refresh_token = _facade().create_refresh_token(user.id, user.username)
    return _facade().auth_token_response(user, access_token, refresh_token)


@_facade().router.post("/auth/login")
def api_login(body: LoginDTO):
    user = _facade().authenticate_user(body.username, body.password)
    if not user:
        raise _facade().HTTPException(401, "用户名或密码错误")
    access_token = _facade().create_access_token(
        user.id, user.username, is_admin=bool(user.is_admin)
    )
    refresh_token = _facade().create_refresh_token(user.id, user.username)
    return _facade().auth_token_response(user, access_token, refresh_token)


@_facade().router.get("/auth/me")
def api_me(user: _facade().Optional[_facade().User] = _facade().Depends(_get_optional_user)):
    if not user:
        return {"ok": False, "success": False, "error": "请先登录"}
    exp = int(getattr(user, "experience", 0) or 0)
    level_profile = _facade().account_level_service.build_level_profile(exp).to_dict()
    from modstore_server.user_avatar_service import public_avatar_url_for_user

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        "company": getattr(user, "company", "") or "",
        "created_at": user.created_at.isoformat() if user.created_at else "",
        "experience": exp,
        "level_profile": level_profile,
        "avatar_url": public_avatar_url_for_user(user),
        **_facade().lifecycle_for_user_id(int(user.id)).to_dict(),
    }


@_facade().router.post("/auth/send-code", status_code=202)
def api_send_code(body: SendCodeDTO, background_tasks: _facade().BackgroundTasks):
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    user = _facade().find_user_by_email(email_norm)
    if not user:
        raise _facade().HTTPException(404, "该邮箱未注册")
    try:
        _facade().assert_email_outbound_configured()
    except RuntimeError as e:
        raise _facade().HTTPException(500, str(e))
    code = _facade().generate_verification_code()
    sf = _facade().get_session_factory()
    with sf() as session:
        vc = _facade().VerificationCode(
            email=email_norm,
            code=code,
            expires_at=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()
    background_tasks.add_task(
        _facade()._background_send_verification_email, email_norm, code, "login"
    )
    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@_facade().router.post("/auth/send-register-code", status_code=202)
def api_send_register_code(body: SendCodeDTO, background_tasks: _facade().BackgroundTasks):
    """向未注册邮箱发送注册验证码：先 202 落库，再异步 SMTP。"""
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    if _facade().find_user_by_email(email_norm):
        raise _facade().HTTPException(409, "该邮箱已注册")
    try:
        _facade().assert_email_outbound_configured()
    except RuntimeError as e:
        raise _facade().HTTPException(500, str(e))
    code = _facade().generate_verification_code()
    sf = _facade().get_session_factory()
    with sf() as session:
        vc = _facade().VerificationCode(
            email=email_norm,
            code=code,
            expires_at=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()
    background_tasks.add_task(
        _facade()._background_send_verification_email, email_norm, code, "register"
    )
    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@_facade().router.post("/auth/login-with-code")
def api_login_with_code(body: LoginWithCodeDTO):
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    user = _facade().find_user_by_email(email_norm)
    if not user:
        raise _facade().HTTPException(404, "该邮箱未注册")
    sf = _facade().get_session_factory()
    with sf() as session:
        vc = (
            session.query(_facade().VerificationCode)
            .filter(
                _facade().VerificationCode.email == email_norm,
                _facade().VerificationCode.code == (body.code or "").strip(),
                _facade().VerificationCode.used.is_(False),
                _facade().VerificationCode.expires_at
                > _facade().datetime.now(_facade().timezone.utc),
            )
            .order_by(_facade().VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise _facade().HTTPException(401, "验证码无效或已过期")
        vc.used = True
        session.commit()
    access_token = _facade().create_access_token(
        user.id, user.username, is_admin=bool(user.is_admin)
    )
    refresh_token = _facade().create_refresh_token(user.id, user.username)
    return _facade().auth_token_response(user, access_token, refresh_token)


@_facade().router.post("/auth/send-reset-password-code", status_code=202)
def api_send_reset_password_code(body: SendCodeDTO, background_tasks: _facade().BackgroundTasks):
    """忘记密码：向已注册邮箱发送验证码（未注册邮箱返回相同提示，不泄露是否存在）。"""
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    user = _facade().find_user_by_email(email_norm)
    if not user:
        return {"ok": True, "message": "如果该邮箱已注册，将收到验证码邮件", "queued": True}
    try:
        _facade().assert_email_outbound_configured()
    except RuntimeError as e:
        raise _facade().HTTPException(500, str(e))
    code = _facade().generate_verification_code()
    sf = _facade().get_session_factory()
    with sf() as session:
        vc = _facade().VerificationCode(
            email=email_norm,
            code=code,
            expires_at=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(minutes=10),
        )
        session.add(vc)
        session.commit()
    background_tasks.add_task(
        _facade()._background_send_verification_email, email_norm, code, "reset"
    )
    return {"ok": True, "message": "如果该邮箱已注册，将收到验证码邮件", "queued": True}


@_facade().router.post("/auth/reset-password")
def api_reset_password(body: ResetPasswordDTO):
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    _facade()._verify_and_consume_verification_code(email_norm, body.code)
    u = _facade().find_user_by_email(email_norm)
    if not u:
        raise _facade().HTTPException(404, "用户不存在")
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == u.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}


class ProfileUpdateDTO(_facade().BaseModel):
    username: str | None = _facade().Field(None, min_length=2, max_length=64)
    company: str | None = _facade().Field(None, max_length=256)


class PasswordChangeDTO(_facade().BaseModel):
    current_password: str = _facade().Field(..., min_length=1)
    new_password: str = _facade().Field(..., min_length=6, max_length=128)


@_facade().router.put("/auth/profile")
def api_update_profile(
    body: ProfileUpdateDTO, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    un = (body.username or "").strip() if body.username is not None else ""
    company = (body.company or "").strip() if body.company is not None else None
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        if un:
            taken = (
                session.query(_facade().User)
                .filter(_facade().User.username == un, _facade().User.id != user.id)
                .first()
            )
            if taken:
                raise _facade().HTTPException(409, "用户名已被占用")
            row.username = un
        if company is not None:
            row.company = company[:256]
        session.commit()
    return {"ok": True, "username": row.username, "company": getattr(row, "company", "") or ""}


@_facade().router.post("/auth/change-password")
def api_change_password(
    body: PasswordChangeDTO, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        if not _facade().verify_password(body.current_password, row.password_hash):
            raise _facade().HTTPException(400, "当前密码不正确")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@_facade().router.post("/admin/reset-user-password")
def api_admin_reset_user_password(body: AdminResetUserPasswordDTO, request: _facade().Request):
    """凭 ``MODSTORE_ADMIN_RECHARGE_TOKEN`` 重置用户密码；请求头 ``X-Modstore-Recharge-Token`` 与钱包直充一致。"""
    admin_token = (_facade().os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise _facade().HTTPException(
            503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法执行管理员密码重置"
        )
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if client_token != admin_token:
        raise _facade().HTTPException(403, "无效的管理员授权")
    un = (body.username or "").strip()
    if not un:
        raise _facade().HTTPException(400, "请填写用户名")
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.username == un).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@_facade().router.post("/auth/refresh")
def api_refresh_token(body: RefreshTokenDTO):
    """使用刷新令牌获取新的访问令牌"""
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
    return _facade().auth_token_response(user, new_access_token, new_refresh_token)


@_facade().router.get("/admin/status")
def api_admin_status(user: _facade().User = _facade().Depends(_facade()._require_admin)):
    """管理员状态检查。"""
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
