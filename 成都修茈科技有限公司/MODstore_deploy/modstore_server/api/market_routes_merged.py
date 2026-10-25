"""Auto-merged part* modules (debt24)."""

# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from market_routes_part01_part01_part01.py ---
"""Implementation extracted from the public facade module."""


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
    except _facade().HTTPException as exc:
        if exc.status_code != 401:
            raise
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
    except RECOVERABLE_ERRORS:
        logging.exception(
            "Background verification email failed email=%s purpose=%s", email, purpose
        )
        try:
            _facade()._delete_unused_verification_code(email, code)
        except RECOVERABLE_ERRORS:
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
def api_me(
    user: _facade().Optional[_facade().User] = _facade().Depends(_get_optional_user),
):
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
    user = _facade().record_successful_login(int(user.id)) or user
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


# --- from market_routes_part01_part01_part02.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.put("/auth/profile")
def api_update_profile(
    body: ProfileUpdateDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
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
        # B10 修复（DetachedInstanceError）：commit 使 ORM 属性过期，session 关闭后
        # 再访问 row.username 会触发 attribute refresh 失败 -> 500。
        # 必须在 session 关闭前读取返回值；company 为未映射列的内存回显，仅用于契约校验。
        payload = {
            "ok": True,
            "username": row.username,
            "company": getattr(row, "company", "") or "",
        }
    return payload


@_facade().router.post("/auth/change-password")
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
def api_admin_status(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
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


# --- from market_routes_part02_part01_part01.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.get("/wallet/balance")
def api_wallet_balance(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = session.query(_facade().Wallet).filter(_facade().Wallet.user_id == user.id).first()
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.commit()
        return {
            "balance": wallet.balance,
            "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else "",
        }


@_facade().router.post("/wallet/recharge")
def api_wallet_recharge(
    body: RechargeDTO,
    request: _facade().Request,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """管理员线下直充（需密钥）。用户日常充值请使用「支付宝」在钱包页发起。"""
    if not user.is_admin:
        raise _facade().HTTPException(
            403, "仅管理员可使用 Token 直充接口，且只能为当前登录账号加款"
        )
    admin_token = (_facade().os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise _facade().HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法直充")
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip() or (
        body.recharge_token or ""
    ).strip()
    if client_token != admin_token:
        raise _facade().HTTPException(403, "无效的充值授权")
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance += body.amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=body.amount,
            txn_type="recharge",
            status="completed",
            description=body.description or "管理员充值",
        )
        session.add(txn)
        session.commit()
        return {"ok": True, "new_balance": wallet.balance}


def _admin_self_credit_cap() -> float:
    raw = (_facade().os.environ.get("MODSTORE_ADMIN_SELF_CREDIT_CAP") or "").strip()
    if not raw:
        return 100000.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 100000.0


@_facade().router.post("/wallet/admin-self-credit")
def api_wallet_admin_self_credit(
    body: AdminSelfCreditDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """管理员为本人钱包加款（仅 JWT 鉴权，不依赖 MODSTORE_ADMIN_RECHARGE_TOKEN）。"""
    if not user.is_admin:
        raise _facade().HTTPException(403, "仅管理员可为本人钱包加款")
    cap = _facade()._admin_self_credit_cap()
    if body.amount > cap:
        raise _facade().HTTPException(400, f"单次加款不能超过 {cap:g} 元")
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance += body.amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=body.amount,
            txn_type="admin_self_credit",
            status="completed",
            description=(body.description or "").strip() or "管理员本人加款",
        )
        session.add(txn)
        session.commit()
        return {"ok": True, "new_balance": wallet.balance, "balance": wallet.balance}


@_facade().router.post("/admin/users/{user_id}/wallet/credit")
def api_admin_credit_user_wallet(
    user_id: int,
    body: AdminSelfCreditDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """管理员为指定用户钱包加款。"""
    amount = _facade()._wallet_money(body.amount)
    if amount <= _facade().Decimal("0.00"):
        raise _facade().HTTPException(400, "加款金额必须大于 0")
    description = (body.description or "").strip() or "后台加款"
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user_id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user_id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance = _facade()._wallet_money(wallet.balance) + amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user_id,
            amount=amount,
            txn_type="admin_credit",
            status="completed",
            description=description,
            idempotency_key=f"admin_credit:{user_id}:{_facade().uuid.uuid4().hex}",
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "amount": _facade()._wallet_money_str(amount),
            "balance": _facade()._wallet_money_str(wallet.balance),
            "new_balance": _facade()._wallet_money_str(wallet.balance),
        }


def _wallet_money(value: _facade().Any) -> _facade().Decimal:
    try:
        return (
            _facade()
            .Decimal(str(value or "0"))
            .quantize(_facade().Decimal("0.01"), rounding=_facade().ROUND_HALF_UP)
        )
    except RECOVERABLE_ERRORS:
        return _facade().Decimal("0.00")


def _wallet_money_str(value: _facade().Any) -> str:
    return format(_facade()._wallet_money(value), "f")


def _ai_hold_no(user_id: int, idempotency_key: str) -> str:
    raw = f"{int(user_id)}:{idempotency_key}".encode("utf-8")
    return "AIH" + _facade().hashlib.sha256(raw).hexdigest()[:16].upper()


def _ai_wallet_meta(**payload: _facade().Any) -> str:
    return "ai_wallet:" + _facade().json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    )


def _parse_ai_wallet_meta(description: str) -> dict[str, _facade().Any]:
    raw = str(description or "")
    if not raw.startswith("ai_wallet:"):
        return {}
    try:
        data = _facade().json.loads(raw[len("ai_wallet:") :])
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ai_wallet_transaction_payload(
    txn: _facade().Transaction,
) -> dict[str, _facade().Any]:
    meta = _facade()._parse_ai_wallet_meta(txn.description)
    return {
        "id": txn.id,
        "amount": _facade()._wallet_money_str(txn.amount),
        "txn_type": txn.txn_type,
        "status": txn.status,
        "hold_no": meta.get("hold_no") or "",
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "request_id": meta.get("request_id") or "",
        "idempotency_key": getattr(txn, "idempotency_key", "") or "",
        "created_at": txn.created_at.isoformat() if txn.created_at else "",
    }


def _find_ai_preauth_by_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Transaction | None:
    rows = (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == "ai_preauth",
        )
        .order_by(_facade().Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        if str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "") == hold_no:
            return row
    return None


def _find_ai_txn_by_key(
    session: _facade().Any, user_id: int, txn_type: str, idempotency_key: str
) -> _facade().Transaction | None:
    return (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == txn_type,
            _facade().Transaction.idempotency_key == idempotency_key,
        )
        .first()
    )


def _ai_txns_for_hold(
    session: _facade().Any, user_id: int, txn_type: str, hold_no: str
) -> list[_facade().Transaction]:
    rows = (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == txn_type,
        )
        .order_by(_facade().Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        row
        for row in rows
        if str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "") == hold_no
    ]


def _ai_settled_amount_for_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Decimal:
    settled = _facade().Decimal("0.00")
    for row in _facade()._ai_txns_for_hold(session, user_id, "ai_settle", hold_no):
        meta = _facade()._parse_ai_wallet_meta(row.description)
        settled = max(
            settled,
            _facade()._wallet_money(meta.get("actual_amount") or abs(row.amount or 0)),
        )
    return settled


def _ai_refunded_amount_for_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Decimal:
    return sum(
        (
            _facade()._wallet_money(row.amount)
            for row in _facade()._ai_txns_for_hold(session, user_id, "ai_refund", hold_no)
        ),
        _facade().Decimal("0.00"),
    )


def _ai_hold_payload(
    preauth: _facade().Transaction, *, status: str, settled_amount: _facade().Any = 0
) -> dict[str, _facade().Any]:
    meta = _facade()._parse_ai_wallet_meta(preauth.description)
    return {
        "hold_no": meta.get("hold_no") or "",
        "amount": _facade()._wallet_money_str(abs(_facade()._wallet_money(preauth.amount))),
        "settled_amount": _facade()._wallet_money_str(settled_amount),
        "status": status,
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "request_id": meta.get("request_id") or "",
        "preauth_transaction_id": preauth.id,
        "created_at": preauth.created_at.isoformat() if preauth.created_at else "",
    }


@_facade().router.post("/wallet/ai/preauthorize")
def api_wallet_ai_preauthorize(
    body: AiWalletPreauthorizeDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """Python 支付后端的 AI 钱包预授权；Java 后端同路径由 proxy 透传。"""
    amount = _facade()._wallet_money(body.amount)
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_preauth", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(existing, status="held"),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        balance_before = _facade()._wallet_money(wallet.balance)
        if balance_before < amount:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{_facade()._wallet_money_str(amount)}，当前 ¥{_facade()._wallet_money_str(balance_before)}",
            )
        hold_no = _facade()._ai_hold_no(user.id, key)
        wallet.balance = balance_before - amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-amount,
            txn_type="ai_preauth",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=hold_no,
                provider=body.provider[:64],
                model=body.model[:128],
                request_id=body.request_id[:128],
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(txn, status="held"),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


# --- from market_routes_part02_part01_part02.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.post("/wallet/ai/settle")
def api_wallet_ai_settle(
    body: AiWalletSettleDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """结算 AI 预授权：实际金额低于预授权则释放差额，高于则补扣差额。"""
    actual = _facade()._wallet_money(body.actual_amount)
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_settle", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(
                    preauth, status="settled", settled_amount=actual
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        delta = actual - reserved
        balance_before = _facade()._wallet_money(wallet.balance)
        if delta > 0 and balance_before < delta:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{_facade()._wallet_money_str(delta)}，当前 ¥{_facade()._wallet_money_str(balance_before)}",
            )
        wallet.balance = balance_before - delta
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-delta,
            txn_type="ai_settle",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(),
                actual_amount=_facade()._wallet_money_str(actual),
                reserved_amount=_facade()._wallet_money_str(reserved),
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=actual),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/release")
def api_wallet_ai_release(
    body: AiWalletReleaseDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """释放 AI 预授权；已结算的 hold 不再退回，保持幂等。"""
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_release", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        settled = (
            session.query(_facade().Transaction)
            .filter(
                _facade().Transaction.user_id == user.id,
                _facade().Transaction.txn_type == "ai_settle",
            )
            .order_by(_facade().Transaction.created_at.desc())
            .limit(200)
            .all()
        )
        if any(
            (
                str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "")
                == body.hold_no.strip()
                for row in settled
            )
        ):
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        wallet.balance = _facade()._wallet_money(wallet.balance) + reserved
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=reserved,
            txn_type="ai_release",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(), reason=(body.reason or "release")[:128]
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/refund")
def api_wallet_ai_refund(
    body: AiWalletRefundDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """Refund a settled AI wallet hold. The idempotency key makes retries safe."""
    key = body.idempotency_key.strip()
    hold_no = body.hold_no.strip()
    refund_amount = _facade()._wallet_money(body.refund_amount)
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_refund", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, hold_no)
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        settled_amount = _facade()._ai_settled_amount_for_hold(session, user.id, hold_no)
        if settled_amount <= 0:
            raise _facade().HTTPException(400, "预授权尚未结算，不能退款")
        if existing:
            return {
                "ok": True,
                "refund": {
                    "hold_no": hold_no,
                    "amount": _facade()._wallet_money_str(existing.amount),
                    "status": "refunded",
                    "refund_transaction_id": existing.id,
                },
                "hold": _facade()._ai_hold_payload(
                    preauth, status="refunded", settled_amount=settled_amount
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        refunded_before = _facade()._ai_refunded_amount_for_hold(session, user.id, hold_no)
        refundable = settled_amount - refunded_before
        if refund_amount > refundable:
            raise _facade().HTTPException(
                400,
                f"退款金额超过可退余额：申请 ¥{_facade()._wallet_money_str(refund_amount)}，可退 ¥{_facade()._wallet_money_str(refundable)}",
            )
        wallet.balance = _facade()._wallet_money(wallet.balance) + refund_amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=refund_amount,
            txn_type="ai_refund",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=hold_no,
                refund_amount=_facade()._wallet_money_str(refund_amount),
                settled_amount=_facade()._wallet_money_str(settled_amount),
                refunded_total_after=_facade()._wallet_money_str(refunded_before + refund_amount),
                reason=(body.reason or "refund")[:128],
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return {
            "ok": True,
            "refund": {
                "hold_no": hold_no,
                "amount": _facade()._wallet_money_str(refund_amount),
                "status": "refunded",
                "refund_transaction_id": txn.id,
            },
            "hold": _facade()._ai_hold_payload(
                preauth, status="refunded", settled_amount=settled_amount
            ),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.get("/wallet/transactions")
def api_wallet_transactions(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .count()
        )
        rows = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .order_by(_facade().Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "transactions": [
                {
                    "id": r.id,
                    "amount": r.amount,
                    "type": r.txn_type,
                    "status": r.status,
                    "description": r.description,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.post("/market/catalog/{item_id}/buy")
def api_buy_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        if not _facade()._market_item_public(item):
            raise _facade().HTTPException(404, "商品不存在")
        from modstore_server.catalog_store import market_item_available

        if not market_item_available(item):
            raise _facade().HTTPException(404, "商品文件不可用")
        if item.price <= 0:
            existing = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id,
                    _facade().Purchase.catalog_id == item.id,
                )
                .first()
            )
            from modstore_server.market_shared import _grant_catalog_entitlement

            if existing:
                _grant_catalog_entitlement(
                    session, user_id=user.id, item=item, source="free_catalog"
                )
                session.commit()
                return {"ok": True, "message": "已拥有"}
            purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=0)
            session.add(purchase)
            _grant_catalog_entitlement(session, user_id=user.id, item=item, source="free_catalog")
            session.commit()
            return {"ok": True, "message": "免费领取成功"}
        existing = (
            session.query(_facade().Purchase)
            .filter(
                _facade().Purchase.user_id == user.id,
                _facade().Purchase.catalog_id == item.id,
            )
            .first()
        )
        if existing:
            return {"ok": True, "message": "已拥有"}
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            session.add(_facade().Wallet(user_id=user.id, balance=0.0))
            session.flush()
            wallet = (
                session.query(_facade().Wallet)
                .filter(_facade().Wallet.user_id == user.id)
                .with_for_update()
                .first()
            )
        if not wallet or wallet.balance < item.price:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{item.price}，当前 ¥{(wallet.balance if wallet else 0)}",
            )
        wallet.balance -= item.price
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=item.price)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-item.price,
            txn_type="purchase",
            status="completed",
            description=f"购买 {item.name} ({item.pkg_id})",
        )
        session.add(purchase)
        session.add(txn)
        session.commit()
        return {"ok": True, "message": "购买成功", "new_balance": wallet.balance}


@_facade().router.get("/market/catalog/{item_id}/download")
def api_download_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        purchased = (
            session.query(_facade().Purchase)
            .filter(
                _facade().Purchase.user_id == user.id,
                _facade().Purchase.catalog_id == item.id,
            )
            .first()
        )
        if not _facade()._market_item_visible_to_user(item, user, purchased=bool(purchased)):
            raise _facade().HTTPException(404, "商品不存在")
        if item.price > 0 and not purchased and not (user.is_admin or item.author_id == user.id):
            raise _facade().HTTPException(403, "未购买此商品，请先购买后下载")
        if not item.stored_filename:
            raise _facade().HTTPException(404, "该商品无文件可下载")
        from fastapi.responses import StreamingResponse

        from modstore_server.catalog_store import market_archive_path

        path = market_archive_path(item.stored_filename, item.sha256)
        if path is None:
            raise _facade().HTTPException(404, "文件缺失或摘要不符")

        def generate():
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={item.pkg_id}.zip",
                "Content-Length": str(path.stat().st_size),
            },
        )


# --- from market_routes_part02_part01_part03.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.get("/my-store")
def api_my_store(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = (
            session.query(_facade().Purchase).filter(_facade().Purchase.user_id == user.id).count()
        )
        rows = (
            session.query(_facade().Purchase)
            .filter(_facade().Purchase.user_id == user.id)
            .order_by(_facade().Purchase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = []
        for p in rows:
            item = (
                session.query(_facade().CatalogItem)
                .filter(_facade().CatalogItem.id == p.catalog_id)
                .first()
            )
            if item:
                items.append(
                    {
                        "purchase_id": p.id,
                        "catalog_id": item.id,
                        "pkg_id": item.pkg_id,
                        "version": item.version,
                        "name": item.name,
                        "artifact": item.artifact or "mod",
                        "price_paid": p.amount,
                        "purchased_at": p.created_at.isoformat() if p.created_at else "",
                    }
                )
        return {"items": items, "total": total}


def _catalog_files_dir() -> _facade().Path:
    from modstore_server.catalog_store import files_dir

    return files_dir()


def _upload_chunks_dir() -> _facade().Path:
    """分块上传临时目录。"""
    d = _facade().Path(__file__).resolve().parent / "upload_chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- from market_routes_part03_part01_part01.py ---
"""Implementation extracted from the public facade module."""


def _existing_child_file(parent: _facade().Path, name: str) -> _facade().Path | None:
    try:
        with _facade().os.scandir(parent) as entries:
            for entry in entries:
                if (
                    entry.name == name
                    and (not entry.is_symlink())
                    and entry.is_file(follow_symlinks=False)
                ):
                    return _facade().Path(entry.path)
    except OSError:
        return None
    return None


def _existing_upload_session(session_id: str) -> _facade().Path | None:
    try:
        with _facade().os.scandir(_facade()._upload_chunks_dir()) as entries:
            for entry in entries:
                if (
                    entry.name == session_id
                    and (not entry.is_symlink())
                    and entry.is_dir(follow_symlinks=False)
                ):
                    return _facade().Path(entry.path)
    except OSError:
        return None
    return None


def _catalog_suffix(raw_name: str) -> str | None:
    raw = str(raw_name or "").lower()
    suffix = raw if raw in {".zip", ".xcmod", ".xcemp"} else _facade().Path(raw).suffix.lower()
    return {".zip": ".zip", ".xcmod": ".xcmod", ".xcemp": ".xcemp"}.get(suffix)


def _new_catalog_file(suffix: str) -> tuple[_facade().Path, str]:
    safe_suffix = {".zip": ".zip", ".xcmod": ".xcmod", ".xcemp": ".xcemp"}.get(suffix)
    if safe_suffix is None:
        raise ValueError("unsupported catalog suffix")
    name = f"{_facade().uuid.uuid4().hex}{safe_suffix}"
    return (_facade()._catalog_files_dir() / name, name)


def _compute_sha256(file_path: _facade().Path) -> str:
    """计算文件 SHA256。"""
    h = _facade().hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class UploadSession(_facade().BaseModel):
    """上传会话信息"""

    session_id: str
    file_name: str
    total_size: int
    chunk_size: int
    total_chunks: int


class UploadChunk(_facade().BaseModel):
    """文件块信息"""

    session_id: str
    chunk_index: int
    chunk_data: bytes


class CompleteUpload(_facade().BaseModel):
    """完成上传请求"""

    session_id: str
    pkg_id: str
    version: str
    name: str
    description: str = ""
    price: float = 0.0
    artifact: str = "mod"
    industry: str = "通用"


class CatalogItemAdminPatchDTO(_facade().BaseModel):
    """管理员调整目录行是否进入公开 AI 市场。"""

    is_public: bool


@_facade().router.post("/admin/catalog", summary="管理员上传 MOD 到市场（支持文件上传）")
async def api_admin_upload_catalog(
    pkg_id: str = _facade().Form(..., min_length=1, max_length=128),
    version: str = _facade().Form(..., min_length=1, max_length=32),
    name: str = _facade().Form(..., min_length=1, max_length=256),
    description: str = _facade().Form(""),
    price: float = _facade().Form(0, ge=0),
    artifact: str = _facade().Form("mod"),
    industry: str = _facade().Form("通用"),
    is_public: bool = _facade().Form(False),
    file: _facade().UploadFile = _facade().File(None),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = (
            session.query(_facade().CatalogItem)
            .filter(
                _facade().CatalogItem.pkg_id == pkg_id,
                _facade().CatalogItem.version == version,
            )
            .first()
        )
        if existing:
            raise _facade().HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")
        stored_filename = ""
        sha256 = ""
        if file and file.filename:
            suffix = _facade()._catalog_suffix(file.filename)
            if suffix is None:
                raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
            dest_path, dest_name = _facade()._new_catalog_file(suffix)
            content = await file.read()
            if len(content) > 100 * 1024 * 1024:
                raise _facade().HTTPException(400, "文件过大（>100MB）")
            dest_path.write_bytes(content)
            stored_filename = dest_name
            sha256 = _facade()._compute_sha256(dest_path)
        ind = (industry or "").strip() or "通用"
        item = _facade().CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=stored_filename,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
        }


@_facade().router.patch("/admin/catalog/{item_id}", summary="更新商品是否对 AI 市场公开展示")
def api_admin_patch_catalog_item(
    item_id: int,
    body: CatalogItemAdminPatchDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """入库默认不公开展示；需要上架时 ``PATCH {"is_public": true}``。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        item.is_public = bool(body.is_public)
        session.commit()
    from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

    _invalidate_market_catalog_caches()
    return {"ok": True, "id": item_id, "is_public": bool(body.is_public)}


@_facade().router.post(
    "/admin/catalog/sync-from-xc-packages",
    summary="从 XC catalog_store 同步缺失条目到市场库",
)
def api_admin_sync_xc_catalog_packages(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """将 ``packages.json`` 中尚未出现在 ``catalog_items`` 的包插入数据库（可选复制文件）。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        out = _facade().catalog_sync.sync_packages_json_to_catalog_items(
            session, admin_user_id=user.id
        )
        session.commit()
    return {"ok": True, **out}


@_facade().router.get("/admin/catalog")
def api_admin_list_catalog(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().CatalogItem).count()
        rows = (
            session.query(_facade().CatalogItem)
            .order_by(_facade().CatalogItem.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "pkg_id": r.pkg_id,
                    "version": r.version,
                    "name": r.name,
                    "description": r.description,
                    "price": r.price,
                    "artifact": r.artifact,
                    "industry": getattr(r, "industry", None) or "通用",
                    "stored_filename": r.stored_filename,
                    "sha256": r.sha256,
                    "is_public": r.is_public,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    **_facade().employee_partition_meta(r.pkg_id, r.artifact),
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.post("/admin/upload/initiate", summary="初始化分块上传")
def api_initiate_upload(
    file_name: str = _facade().Form(...),
    total_size: int = _facade().Form(...),
    chunk_size: int = _facade().Form(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """初始化分块上传会话"""
    session_id = str(_facade().uuid.uuid4())
    suffix = _facade()._catalog_suffix(file_name)
    if suffix is None:
        raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
    if total_size <= 0 or chunk_size <= 0:
        raise _facade().HTTPException(400, "上传大小参数无效")
    total_chunks = (total_size + chunk_size - 1) // chunk_size
    if total_chunks > 10000:
        raise _facade().HTTPException(400, "文件分块过多")
    session_dir = _facade()._upload_chunks_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session_info = {
        "session_id": session_id,
        "suffix": suffix,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "created_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
    }
    with open(session_dir / "session.json", "w", encoding="utf-8") as f:
        _facade().json.dump(session_info, f)
    return {"ok": True, "session_id": session_id, "total_chunks": total_chunks}


@_facade().router.post("/admin/upload/chunk", summary="上传文件块")
async def api_upload_chunk(
    session_id: str = _facade().Form(...),
    chunk_index: int = _facade().Form(...),
    file: _facade().UploadFile = _facade().File(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """上传单个文件块"""
    session_dir = _facade()._existing_upload_session(session_id)
    if session_dir is None:
        raise _facade().HTTPException(404, "上传会话不存在")
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = _facade().json.load(f)
    total_chunks = int(session_info["total_chunks"])
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise _facade().HTTPException(400, "无效的块索引")
    chunk_name = tuple((f"chunk_{i}" for i in range(total_chunks)))[chunk_index]
    chunk_path = session_dir / chunk_name
    content = await file.read()
    with open(chunk_path, "wb") as f:
        f.write(content)
    return {"ok": True, "chunk_index": chunk_index}


@_facade().router.post("/admin/upload/complete", summary="完成分块上传")
def api_complete_upload(
    session_id: str = _facade().Form(...),
    pkg_id: str = _facade().Form(...),
    version: str = _facade().Form(...),
    name: str = _facade().Form(...),
    description: str = _facade().Form(""),
    price: float = _facade().Form(0.0),
    artifact: str = _facade().Form("mod"),
    industry: str = _facade().Form("通用"),
    is_public: bool = _facade().Form(False),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """完成分块上传并合并文件"""
    session_dir = _facade()._existing_upload_session(session_id)
    if session_dir is None:
        raise _facade().HTTPException(404, "上传会话不存在")
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = _facade().json.load(f)
    missing_chunks = []
    for i in range(session_info["total_chunks"]):
        chunk_path = session_dir / f"chunk_{i}"
        if not chunk_path.exists():
            missing_chunks.append(i)
    if missing_chunks:
        raise _facade().HTTPException(400, f"缺少文件块: {missing_chunks}")
    suffix = _facade()._catalog_suffix(str(session_info.get("suffix") or ""))
    if suffix is None:
        raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
    dest_path, dest_name = _facade()._new_catalog_file(suffix)
    with open(dest_path, "wb") as out_file:
        for i in range(session_info["total_chunks"]):
            chunk_path = session_dir / f"chunk_{i}"
            with open(chunk_path, "rb") as in_file:
                out_file.write(in_file.read())
    sha256 = _facade()._compute_sha256(dest_path)
    import shutil

    shutil.rmtree(session_dir)
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = (
            session.query(_facade().CatalogItem)
            .filter(
                _facade().CatalogItem.pkg_id == pkg_id,
                _facade().CatalogItem.version == version,
            )
            .first()
        )
        if existing:
            raise _facade().HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")
        ind = (industry or "").strip() or "通用"
        item = _facade().CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=dest_name,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
            "file_size": session_info["total_size"],
        }


# --- from market_routes_part03_part01_part02.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.delete("/admin/catalog/{item_id}")
def api_admin_delete_catalog(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    """管理员下架商品（幂等 soft-delete）。

    - 不再 hard delete 行：``Purchase`` / ``Review`` / ``Favorite`` / ``Entitlement``
      均通过 ``ForeignKey(catalog_items.id)`` 引用本表（部分 ``nullable=False``），
      硬删会破坏对账与历史，且重复点击会立即触发 404。
    - 改为打 ``compliance_status='delisted'`` + ``is_public=False``：公开目录
      （``CatalogItem.compliance_status != 'delisted'``）即不再展示，
      与前端按钮文案 “下架后 AI 市场将不再展示该商品” 语义一致。
    - 同步从 ``packages.json``（``/v1/packages`` 数据源）移除条目，删除其下
      ``catalog_data/files/`` 中的二进制保留以便已购用户下载和后续恢复。
    - 幂等：行不存在或已下架时返回 ``ok: True`` 且不报 404，避免前端列表因
      60s 缓存或多实例 (``upstream modstore_api``) 视图差异在重复点击时失败。
    """
    from modstore_server import catalog_store

    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            return {
                "ok": True,
                "deleted_id": item_id,
                "already_missing": True,
                "already_delisted": False,
                "removed_catalog_store": 0,
            }
        already_delisted = (item.compliance_status or "") == "delisted"
        pkg_id = item.pkg_id or ""
        if not already_delisted:
            item.is_public = False
            item.compliance_status = "delisted"
            item.delist_reason = "管理员手动下架"
            item.rank_score = 0.0
            session.commit()
    n_json = catalog_store.remove_package(pkg_id, version=None, remove_files=False) if pkg_id else 0
    try:
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()
    except RECOVERABLE_ERRORS:
        pass
    return {
        "ok": True,
        "deleted_id": item_id,
        "already_missing": False,
        "already_delisted": already_delisted,
        "removed_catalog_store": n_json,
    }


@_facade().router.delete("/admin/employee-packs/{pkg_id:path}")
def api_admin_delete_employee_pack(
    pkg_id: str, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    """删除员工包：清掉本地 ``/v1`` catalog（``packages.json`` + ``files/``）中该 ``pkg_id`` 全部版本，并删除 ``catalog_items`` 中 ``artifact=employee_pack`` 的登记行。"""
    from modstore_server import catalog_store
    from modstore_server.duty_roster import all_planned_employee_ids

    pid = catalog_store.norm_pkg_id(pkg_id)
    if not pid:
        raise _facade().HTTPException(400, "pkg_id 无效")
    if pid in all_planned_employee_ids():
        raise _facade().HTTPException(
            403,
            "该员工包属于编制在岗岗位（duty_roster / 员工工作流管理矩阵），禁止删除。若确需移除，请先从 yuangon 编制与 duty_roster.py 中调整岗位列表后再操作。",
        )
    n_json = catalog_store.remove_package(pid, version=None)
    removed_db = False
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().CatalogItem)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .all()
        )
        to_delete = [x for x in rows if catalog_store.norm_pkg_id(x.pkg_id) == pid]
        for item in to_delete:
            if item.stored_filename:
                file_path = _facade()._catalog_files_dir() / item.stored_filename
                if file_path.is_file():
                    file_path.unlink()
            session.delete(item)
        if to_delete:
            session.commit()
            removed_db = True
    return {
        "ok": True,
        "removed_catalog_store": n_json,
        "removed_db": removed_db,
        "already_absent": n_json == 0 and (not removed_db),
    }


@_facade().router.post("/admin/employee-packs/align-llm-from-deepseek")
async def api_admin_align_employee_llm_from_deepseek(
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包批量改为当前环境下首个可用 LLM（平台密钥或作者 BYOK），并执行与 employee-save 相同的落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_from_deepseek,
    )

    return await align_catalog_employee_packs_llm_from_deepseek(user, dry_run=dry_run)


@_facade().router.post("/admin/employee-packs/align-llm-to-auto")
async def api_admin_align_employee_llm_to_auto(
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包改为 manifest 内 ``provider=model_name=auto``（工作台「自动」），与 employee-save 相同落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_to_auto_sentinel,
    )

    return await align_catalog_employee_packs_llm_to_auto_sentinel(user, dry_run=dry_run)


@_facade().router.post("/admin/employee-packs/{pkg_id}/align-llm-to-auto-single")
async def api_admin_align_single_employee_llm_to_auto(
    pkg_id: str,
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """单个员工包的 LLM 绑定改为 ``provider=model_name=auto``，不再受 provider==deepseek 过滤。

    用于「无密钥」修复路径：管理员在 dg-stats 上直接点单条「改为自动」时调用。
    """
    from modstore_server.employee_pack_deepseek_align import align_single_employee_pack_llm_to_auto

    result = await align_single_employee_pack_llm_to_auto(user, pkg_id, dry_run=dry_run)
    if not result.get("ok"):
        raise _facade().HTTPException(400, str(result.get("error") or "对齐失败"))
    return result


@_facade().router.post("/admin/employee-packs/purge-all")
def api_admin_purge_all_employee_packs(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """一键清空商店员工包，保留管理端上岗员工。

    上岗员工由 ``duty_roster.py``/编制矩阵管理；商店清理不得删除这些岗位包。"""
    from modstore_server import catalog_store

    removed_packages = 0
    removed_files = 0
    preserved_duty_packages = 0
    with catalog_store._lock:
        data = catalog_store.load_store()
        kept = []
        for r in data.get("packages") or []:
            if str((r or {}).get("artifact") or "") == "employee_pack":
                pid = str((r or {}).get("id") or (r or {}).get("pkg_id") or "").strip()
                if _facade().is_planned_duty_employee_pack(pid, "employee_pack"):
                    preserved_duty_packages += 1
                    kept.append(r)
                    continue
                fn = str((r or {}).get("stored_filename") or "").strip()
                if fn:
                    p = catalog_store.files_dir() / fn
                    if p.is_file():
                        try:
                            p.unlink()
                            removed_files += 1
                        except OSError:
                            pass
                removed_packages += 1
                continue
            kept.append(r)
        data["packages"] = kept
        catalog_store.save_store(data)
    removed_db = 0
    preserved_duty_db_rows = 0
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().CatalogItem)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .all()
        )
        for item in rows:
            if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
                preserved_duty_db_rows += 1
                continue
            stored = (item.stored_filename or "").strip()
            if stored:
                p = _facade()._catalog_files_dir() / stored
                if p.is_file():
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass
            session.delete(item)
        if rows:
            session.commit()
            removed_db = len(rows)
    return {
        "ok": True,
        "removed_packages_json": removed_packages,
        "removed_db_rows": removed_db,
        "removed_files": removed_files,
        "preserved_duty_packages_json": preserved_duty_packages,
        "preserved_duty_db_rows": preserved_duty_db_rows,
    }


@_facade().router.post("/admin/mods/purge-all")
def api_admin_purge_all_mods(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """一键清空 mod 源码库：删除 ``library/`` 下所有 mod 目录（仅限带 manifest.json
    的子目录），并截断 ``user_mods`` 关联表。

    用于「重置仓库」语义——前端列表合并了多个数据源，逐条删除容易因 list 缓存、
    norm 不一致、user_mods 关联残留导致「老是删不完」。这里一次性原子清空。"""
    from modman.repo_config import load_config, resolved_library
    from modman.store import iter_mod_dirs
    from modstore_server.models import UserMod

    lib = resolved_library(load_config())
    removed_dirs: _facade().List[str] = []
    if lib.is_dir():
        for d in list(iter_mod_dirs(lib)):
            try:
                _facade().shutil.rmtree(d, ignore_errors=False)
                removed_dirs.append(d.name)
            except OSError:
                pass
    sf = _facade().get_session_factory()
    with sf() as session:
        removed_user_mod_rows = session.query(UserMod).delete()
        session.commit()
    return {
        "ok": True,
        "removed_dirs": removed_dirs,
        "removed_dir_count": len(removed_dirs),
        "removed_user_mod_rows": int(removed_user_mod_rows or 0),
    }


# --- from market_routes_part04.py ---
"""Implementation extracted from the public facade module."""


@_facade().router.get("/admin/users")
def api_admin_list_users(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    is_enterprise: bool | None = _facade().Query(
        None, description="true=仅企业级，false=仅非企业级"
    ),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        q = session.query(_facade().User)
        if is_enterprise is True:
            q = q.filter(_facade().User.is_enterprise.is_(True))
        elif is_enterprise is False:
            q = q.filter(_facade().User.is_enterprise.is_(False))
        total = q.count()
        rows = q.order_by(_facade().User.created_at.desc()).offset(offset).limit(limit).all()
        uid_list = [int(r.id) for r in rows]
        mod_map = _facade()._user_mod_ids_map(uid_list)
        return {
            "users": [
                {
                    "id": r.id,
                    "username": r.username,
                    "email": r.email,
                    "is_admin": r.is_admin,
                    "is_enterprise": bool(getattr(r, "is_enterprise", False)),
                    "mod_ids": mod_map.get(int(r.id), []),
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.put("/admin/users/{user_id}/admin")
def api_admin_set_admin_status(
    user_id: int,
    is_admin: bool = _facade().Query(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        target.is_admin = is_admin
        session.commit()
        return {"ok": True, "user_id": user_id, "is_admin": is_admin}


@_facade().router.put("/admin/users/{user_id}/enterprise")
def api_admin_set_enterprise_status(
    user_id: int,
    is_enterprise: bool = _facade().Query(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        target.is_enterprise = is_enterprise
        target.account_state = (
            _facade().ACCOUNT_ACTIVE if is_enterprise else _facade().ACCOUNT_PENDING_PLAN
        )
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "is_enterprise": is_enterprise,
            **_facade().lifecycle_for_user(session, target).to_dict(),
        }


@_facade().router.get("/admin/enterprise/assignable-mods")
def api_admin_enterprise_assignable_mods(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """返回管理员可分配给企业的客户 Mod 列表。"""
    mods = [
        {"id": mid, "name": _facade().ENTERPRISE_ASSIGNABLE_MODS[mid]}
        for mid in sorted(_facade()._enterprise_assignable_mod_ids())
    ]
    return {"ok": True, "mods": mods}


@_facade().router.get("/admin/users/{user_id}/mods")
def api_admin_list_user_mods(
    user_id: int, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    from modstore_server.models_db import get_user_mod_ids

    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
    mod_ids = sorted(get_user_mod_ids(user_id))
    return {
        "ok": True,
        "user_id": user_id,
        "username": target.username,
        "is_enterprise": bool(getattr(target, "is_enterprise", False)),
        "mod_ids": mod_ids,
    }


@_facade().router.post("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_bind_user_mod(
    user_id: int,
    mod_id: str,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """将 Mod 绑定到用户 user_mods（企业版桌面 entitlement 数据源）。"""
    from modstore_server.models_db import add_user_mod

    mid = _facade()._assert_enterprise_assignable_mod_id(mod_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        if session.query(_facade().User).filter(_facade().User.id == user_id).first() is None:
            raise _facade().HTTPException(404, "用户不存在")
    add_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@_facade().router.delete("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_unbind_user_mod(
    user_id: int,
    mod_id: str,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    from modstore_server.models_db import remove_user_mod

    mid = _facade()._assert_enterprise_assignable_mod_id(mod_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        if session.query(_facade().User).filter(_facade().User.id == user_id).first() is None:
            raise _facade().HTTPException(404, "用户不存在")
    remove_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@_facade().router.get("/enterprise/entitled-mod-ids")
def api_enterprise_entitled_mod_ids(
    user: _facade().User = _facade().Depends(_facade().get_current_user),
):
    """企业版桌面专用：仅返回 user_mods 绑定的 Mod id（不因 is_admin 返回全库）。"""
    from modstore_server.models_db import get_user_mod_ids

    mod_ids = sorted(get_user_mod_ids(user.id))
    return {
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "mod_ids": mod_ids,
    }


@_facade().router.get("/enterprise/customer-delivery-seeds/{pkg_id}/{version}/download")
def api_enterprise_customer_delivery_seed_download(
    pkg_id: str,
    version: str,
    mod_id: str = _facade().Query(""),
    user: _facade().User = _facade().Depends(_facade().get_current_user),
):
    """Download an account-scoped customer seed after enterprise entitlement checks."""
    from fastapi.responses import FileResponse

    from modstore_server.catalog_store import files_dir, get_package
    from modstore_server.models_db import get_user_mod_ids

    pkg = get_package(pkg_id, version)
    if not pkg:
        raise _facade().HTTPException(404, "交付种子包不存在")
    artifact = str(pkg.get("artifact") or "").strip().lower()
    if artifact != "customer_delivery_seed":
        raise _facade().HTTPException(404, "不是客户交付种子包")
    account_mod_id = str(pkg.get("account_mod_id") or "").strip()
    if not account_mod_id:
        raise _facade().HTTPException(403, "交付种子包未绑定客户 Mod")
    requested_mod_id = str(mod_id or account_mod_id).strip()
    if requested_mod_id != account_mod_id:
        raise _facade().HTTPException(403, "交付种子包与请求 Mod 不匹配")
    entitled = set(get_user_mod_ids(int(user.id)))
    if account_mod_id not in entitled:
        raise _facade().HTTPException(403, "当前账号未授权该客户交付包")
    name = str(pkg.get("stored_filename") or "").strip()
    if not name:
        raise _facade().HTTPException(404, "交付种子包无本地文件")
    path = files_dir() / name
    if not path.is_file():
        raise _facade().HTTPException(404, "交付种子文件缺失")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@_facade().router.get("/admin/wallets")
def api_admin_list_wallets(
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Return one wallet row per account, including users whose balance is still zero.

    A wallet record is created lazily on first wallet use.  Listing the ``wallets`` table alone
    therefore made untouched accounts look as if their balance could not be queried.
    """
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().User).count()
        rows = (
            session.query(_facade().User, _facade().Wallet)
            .outerjoin(_facade().Wallet, _facade().Wallet.user_id == _facade().User.id)
            .order_by(_facade().User.created_at.desc(), _facade().User.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": wallet.id if wallet else None,
                    "user_id": account.id,
                    "balance": wallet.balance if wallet else 0.0,
                    "updated_at": (
                        wallet.updated_at.isoformat()
                        if wallet is not None and wallet.updated_at
                        else ""
                    ),
                }
                for (account, wallet) in rows
            ],
            "total": total,
        }


@_facade().router.get("/admin/transactions")
def api_admin_list_transactions(
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().Transaction).count()
        rows = (
            session.query(_facade().Transaction)
            .order_by(_facade().Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": t.id,
                    "user_id": t.user_id,
                    "amount": t.amount,
                    "txn_type": t.txn_type,
                    "status": t.status,
                    "description": t.description,
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                }
                for t in rows
            ],
            "total": total,
        }


@_facade().router.get("/admin/orders")
def api_admin_list_orders(
    status: _facade().Optional[str] = _facade().Query(None),
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """管理员订单/经营看板：分页订单列表 + 全量经营聚合。

    数据源：PAYMENT_BACKEND=java 时 Java PostgreSQL 为 SoT，本地 JSON 为只读兜底；
    其余模式本地 JSON 为权威来源。返回 ``source`` 供前端标注数据来源。
    """
    from modstore_server import payment_orders

    rows, total = payment_orders.list_orders(user_id=0, status=status, limit=limit, offset=offset)
    all_rows, _ = payment_orders.list_orders(user_id=0, status=None, limit=100000, offset=0)
    summary: dict[str, _facade().Any] = {
        "total_orders": len(all_rows),
        "paid_orders": 0,
        "pending_orders": 0,
        "paid_revenue": 0.0,
        "by_status": {},
    }
    for o in all_rows:
        st = str(o.get("status") or "unknown")
        summary["by_status"][st] = summary["by_status"].get(st, 0) + 1
        if st == "paid":
            summary["paid_orders"] += 1
            try:
                summary["paid_revenue"] += _facade().Decimal(str(o.get("total_amount") or "0"))
            except RECOVERABLE_ERRORS:
                pass
        elif st == "pending":
            summary["pending_orders"] += 1
    summary["paid_revenue"] = float(summary["paid_revenue"])
    return {
        "items": rows,
        "total": total,
        "summary": summary,
        "source": "python_json" if payment_orders.is_local_source_of_truth() else "java",
    }


@_facade().router.get("/wallet/overview")
def api_wallet_overview(
    limit: int = _facade().Query(20, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """钱包概览：余额 + 最近交易流水（前端 walletOverview 消费此接口）。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = session.query(_facade().Wallet).filter(_facade().Wallet.user_id == user.id).first()
        balance = wallet.balance if wallet else 0.0
        updated_at = wallet.updated_at.isoformat() if wallet and wallet.updated_at else ""
        total = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .count()
        )
        rows = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .order_by(_facade().Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "wallet": {"balance": balance, "updated_at": updated_at},
            "balance": balance,
            "transactions": [
                {
                    "id": r.id,
                    "amount": r.amount,
                    "type": r.txn_type,
                    "status": r.status,
                    "description": r.description,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.post("/package-audit")
async def api_package_audit(
    file: _facade().UploadFile = _facade().File(...),
    metadata: _facade().Optional[str] = _facade().Form(None),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """通用包审计接口（前端 auditPackage 消费此接口）。上传 .zip/.xcemp，返回五维审核结论。"""
    import json as _json

    from modstore_server.package_sandbox_audit import run_package_audit_async

    raw = await file.read()
    meta: dict = {}
    if metadata:
        try:
            meta = _json.loads(metadata)
        except RECOVERABLE_ERRORS:
            pass
    result = await run_package_audit_async(raw, meta or None)
    return result
