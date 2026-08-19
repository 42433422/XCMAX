# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


@_facade().router.post("/auth/register", summary="注册用户（邮箱选填，填写时需验证）")
def api_register(body: _facade().RegisterDTO):
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
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        },
    }


@_facade().router.post("/auth/login", summary="用户名密码登录，返回 JWT")
def api_login(body: _facade().LoginDTO):
    user = _facade().authenticate_user(body.username, body.password)
    if not user:
        raise _facade().HTTPException(401, "用户名或密码错误")
    access_token = _facade().create_access_token(
        user.id, user.username, is_admin=bool(user.is_admin)
    )
    refresh_token = _facade().create_refresh_token(user.id, user.username)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        },
    }


class InternalSsoIssueTokenDTO(_facade().BaseModel):
    username: str = _facade().Field(default="", max_length=128)
    email: str = _facade().Field(default="", max_length=256)
    oidc_sub: str = _facade().Field(default="", max_length=256)
    display_name: str = _facade().Field(default="", max_length=128)


@_facade().router.post("/auth/internal/sso-issue-token", include_in_schema=False)
def api_internal_sso_issue_token(body: InternalSsoIssueTokenDTO, request: _facade().Request):
    """FHD OIDC 回调后签发 MODstore JWT（Header: X-Internal-Api-Key）。"""
    _facade()._require_internal_api_key(request)
    from modstore_server.auth_service import issue_market_tokens_for_sso_identity

    try:
        data = issue_market_tokens_for_sso_identity(
            username=(body.username or "").strip(),
            email=(body.email or "").strip(),
            oidc_sub=(body.oidc_sub or "").strip(),
            display_name=(body.display_name or "").strip(),
        )
    except ValueError as exc:
        raise _facade().HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": data}


@_facade().router.get("/auth/me", summary="当前用户资料与等级（含 Java 侧叠加字段）")
def api_me(
    request: _facade().Request,
    user: _facade().Optional[_facade().User] = _facade().Depends(_facade()._optional_current_user),
):
    if not user:
        return {"ok": False, "success": False, "error": "请先登录"}
    exp = int(getattr(user, "experience", 0) or 0)
    level_profile = _facade().account_level_service.build_level_profile(exp).to_dict()
    phone_out = (getattr(user, "phone", None) or "") or ""
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    overlay = _facade().fetch_java_user_overlay(auth_header, expect_user_id=int(user.id))
    if overlay is not None:
        exp = int(overlay.experience)
        if isinstance(overlay.level_profile, dict) and overlay.level_profile:
            level_profile = overlay.level_profile
        else:
            level_profile = _facade().account_level_service.build_level_profile(exp).to_dict()
        if overlay.phone:
            phone_out = overlay.phone
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": phone_out,
        "is_admin": user.is_admin,
        "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        "created_at": user.created_at.isoformat() if user.created_at else "",
        "experience": exp,
        "level_profile": level_profile,
        "avatar_url": _facade().public_avatar_url_for_user(user),
    }


@_facade().router.post("/auth/avatar", summary="上传或更换当前用户头像")
async def api_upload_avatar(
    file: _facade().UploadFile = _facade().File(...),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    payload = await file.read()
    (relpath, _mime) = _facade().save_user_avatar(
        int(user.id), payload, file.filename or "avatar.jpg"
    )
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.avatar_path = relpath
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
        version = int(row.avatar_version)
        url = _facade().public_avatar_url_for_user(row)
    return {"ok": True, "avatar_url": url, "avatar_version": version}


@_facade().router.delete("/auth/avatar", summary="移除当前用户头像")
def api_delete_avatar(user: _facade().User = _facade().Depends(_facade()._get_current_user)):
    _facade().delete_user_avatar_files(int(user.id))
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.avatar_path = ""
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
    return {"ok": True, "avatar_url": None}


@_facade().router.get("/auth/avatar/file", summary="读取当前用户头像（需登录）")
def api_avatar_file(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    v: _facade()
    .Optional[int] = _facade()
    .Query(None, description="与 avatar_url 中 v 一致，仅用于缓存校验"),
):
    rel = _facade().avatar_path_column(user)
    if not rel:
        raise _facade().HTTPException(404, "未设置头像")
    if v is not None and int(v) != _facade().avatar_version_column(user):
        raise _facade().HTTPException(404, "头像已更新，请刷新")
    path = _facade().resolve_avatar_file(rel)
    if not path.is_file():
        raise _facade().HTTPException(404, "头像文件不存在")
    suffix = path.suffix.lower()
    media = _facade()._MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    return _facade().FileResponse(path, media_type=media, filename=f"avatar{suffix}")


@_facade().router.post("/auth/send-code", status_code=202, summary="向已注册邮箱发送登录验证码")
def api_send_code(body: _facade().SendCodeDTO, background_tasks: _facade().BackgroundTasks):
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


@_facade().router.post(
    "/auth/send-register-code", status_code=202, summary="向新邮箱发送注册验证码"
)
def api_send_register_code(
    body: _facade().SendCodeDTO, background_tasks: _facade().BackgroundTasks
):
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


@_facade().router.post("/auth/login-with-code", summary="邮箱验证码登录")
def api_login_with_code(body: _facade().LoginWithCodeDTO):
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
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        },
    }


@_facade().router.post(
    "/auth/send-reset-password-code", status_code=202, summary="发送重置密码验证码"
)
def api_send_reset_password_code(
    body: _facade().SendCodeDTO, background_tasks: _facade().BackgroundTasks
):
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


@_facade().router.post("/auth/reset-password", summary="凭邮箱验证码重置密码")
def api_reset_password(body: _facade().ResetPasswordDTO):
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


@_facade().router.put("/auth/profile", summary="修改当前用户显示名")
def api_update_profile(
    body: _facade().ProfileUpdateDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    un = (body.username or "").strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        taken = (
            session.query(_facade().User)
            .filter(_facade().User.username == un, _facade().User.id != user.id)
            .first()
        )
        if taken:
            raise _facade().HTTPException(409, "用户名已被占用")
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.username = un
        session.commit()
    return {"ok": True, "username": un}


@_facade().router.post("/auth/change-password", summary="已登录用户修改密码")
def api_change_password(
    body: _facade().PasswordChangeDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
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


@_facade().router.post(
    "/admin/reset-user-password",
    summary="管理员重置用户密码（MODSTORE_ADMIN_RECHARGE_TOKEN）",
    tags=["auth", "admin"],
)
def api_admin_reset_user_password(
    body: _facade().AdminResetUserPasswordDTO, request: _facade().Request
):
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


@_facade().router.post("/auth/refresh", summary="用 refresh_token 换取新的 access_token")
def api_refresh_token(body: _facade().RefreshTokenDTO):
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
    body: AccountDeleteDTO, user: _facade().User = _facade().Depends(_facade()._get_current_user)
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
def api_account_export(user: _facade().User = _facade().Depends(_facade()._get_current_user)):
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
def api_admin_status(user: _facade().User = _facade().Depends(_facade()._require_admin)):
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
