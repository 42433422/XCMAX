# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.market_auth_api_part01_part01_part02 import (
    AdminResetUserPasswordDTO,
)
from modstore_server.market_auth_api_part01_part01_part02 import LoginDTO
from modstore_server.market_auth_api_part01_part01_part02 import LoginWithCodeDTO
from modstore_server.market_auth_api_part01_part01_part02 import PasswordChangeDTO
from modstore_server.market_auth_api_part01_part01_part02 import ProfileUpdateDTO
from modstore_server.market_auth_api_part01_part01_part02 import RegisterDTO
from modstore_server.market_auth_api_part01_part01_part02 import ResetPasswordDTO
from modstore_server.market_auth_api_part01_part01_part02 import SendCodeDTO


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


@_facade().router.post("/auth/register", summary="注册用户（邮箱选填，填写时需验证）")
def api_register(body: RegisterDTO):
    email_norm, vcode = (
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
def api_login(body: LoginDTO):
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
def api_internal_sso_issue_token(
    body: InternalSsoIssueTokenDTO, request: _facade().Request
):
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
    user: _facade().Optional[_facade().User] = _facade().Depends(
        _facade()._optional_current_user
    ),
):
    if not user:
        return {"ok": False, "success": False, "error": "请先登录"}
    exp = int(getattr(user, "experience", 0) or 0)
    level_profile = _facade().account_level_service.build_level_profile(exp).to_dict()
    phone_out = (getattr(user, "phone", None) or "") or ""
    auth_header = (
        request.headers.get("authorization")
        or request.headers.get("Authorization")
        or ""
    )
    overlay = _facade().fetch_java_user_overlay(
        auth_header, expect_user_id=int(user.id)
    )
    if overlay is not None:
        exp = int(overlay.experience)
        if isinstance(overlay.level_profile, dict) and overlay.level_profile:
            level_profile = overlay.level_profile
        else:
            level_profile = (
                _facade().account_level_service.build_level_profile(exp).to_dict()
            )
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
    relpath, _mime = _facade().save_user_avatar(
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
def api_delete_avatar(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
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
    v: _facade().Optional[int] = _facade().Query(
        None, description="与 avatar_url 中 v 一致，仅用于缓存校验"
    ),
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


@_facade().router.post(
    "/auth/send-code", status_code=202, summary="向已注册邮箱发送登录验证码"
)
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


@_facade().router.post(
    "/auth/send-register-code", status_code=202, summary="向新邮箱发送注册验证码"
)
def api_send_register_code(
    body: SendCodeDTO, background_tasks: _facade().BackgroundTasks
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
    user = _facade().record_successful_login(int(user.id)) or user
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
    body: SendCodeDTO, background_tasks: _facade().BackgroundTasks
):
    email_norm = _facade()._normalize_email(body.email)
    if not email_norm:
        raise _facade().HTTPException(400, "请填写邮箱")
    user = _facade().find_user_by_email(email_norm)
    if not user:
        return {
            "ok": True,
            "message": "如果该邮箱已注册，将收到验证码邮件",
            "queued": True,
        }
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


@_facade().router.put("/auth/profile", summary="修改当前用户显示名")
def api_update_profile(
    body: ProfileUpdateDTO,
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
    body: PasswordChangeDTO,
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
    body: AdminResetUserPasswordDTO, request: _facade().Request
):
    admin_token = (
        _facade().os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or ""
    ).strip()
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
        row = (
            session.query(_facade().User).filter(_facade().User.username == un).first()
        )
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}
