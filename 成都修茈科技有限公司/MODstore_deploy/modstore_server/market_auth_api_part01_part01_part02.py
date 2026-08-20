# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


@_facade().router.get(
    "/internal/cs-intake/enterprise-account",
    summary="客服 · 查询企业客户登录账号（服务间，不含密码明文）",
    tags=["market"],
)
def api_internal_cs_intake_enterprise_account(
    request: _facade().Request, market_user_id: int = _facade().Query(..., gt=0)
):
    _facade()._require_internal_api_key(request)
    uid = int(market_user_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == uid).first()
        if not row:
            raise _facade().HTTPException(status_code=404, detail="用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            raise _facade().HTTPException(status_code=404, detail="用户已注销")
        return {
            "ok": True,
            "user_id": uid,
            "username": str(row.username or "").strip(),
            "email": str(row.email or "").strip(),
            "is_enterprise": bool(getattr(row, "is_enterprise", False)),
        }


class IssueEnterprisePasswordDTO(_facade().BaseModel):
    market_user_id: int = _facade().Field(..., gt=0)
    password: str = _facade().Field(..., min_length=8, max_length=128)


@_facade().router.post(
    "/internal/cs-intake/issue-enterprise-password",
    summary="客服 · 重置企业客户修茈市场登录密码（服务间）",
    tags=["market"],
)
def api_internal_cs_intake_issue_enterprise_password(
    request: _facade().Request, body: IssueEnterprisePasswordDTO
):
    _facade()._require_internal_api_key(request)
    uid = int(body.market_user_id)
    plain = (body.password or "").strip()
    if len(plain) < 8:
        raise _facade().HTTPException(status_code=400, detail="密码至少 8 位")
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == uid).first()
        if not row:
            raise _facade().HTTPException(status_code=404, detail="用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            raise _facade().HTTPException(status_code=404, detail="用户已注销")
        row.password_hash = _facade().hash_password(plain)
        if not row.is_enterprise:
            row.is_enterprise = True
        session.commit()
        return {
            "ok": True,
            "user_id": uid,
            "username": str(row.username or "").strip(),
            "email": str(row.email or "").strip(),
            "is_enterprise": bool(row.is_enterprise),
        }


class LinkCrmDTO(_facade().BaseModel):
    landing_contact_id: int = _facade().Field(..., gt=0)
    crm_opportunity_id: int = _facade().Field(..., gt=0)
    market_user_id: int | None = _facade().Field(default=None, gt=0)


@_facade().router.post(
    "/internal/contact/link-crm",
    summary="客服 · 回写 landing 联系记录与 CRM 商机关联（服务间）",
    tags=["market"],
)
def api_internal_contact_link_crm(request: _facade().Request, body: LinkCrmDTO):
    _facade()._require_internal_api_key(request)
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.get(_facade().LandingContactSubmission, int(body.landing_contact_id))
        if not row:
            raise _facade().HTTPException(status_code=404, detail="未找到该联系表单记录")
        try:
            meta = _facade().json.loads(row.meta_json or "{}")
        except _facade().json.JSONDecodeError:
            meta = {}
        if body.market_user_id:
            bound = int(meta.get("market_user_id") or 0)
            uid = int(body.market_user_id)
            if bound and bound != uid:
                raise _facade().HTTPException(status_code=409, detail="market_user_id 与记录不一致")
            meta["market_user_id"] = uid
        meta["crm_opportunity_id"] = int(body.crm_opportunity_id)
        meta["crm_linked_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
        row.meta_json = _facade().json.dumps(meta, ensure_ascii=False)
        session.commit()
    return {
        "ok": True,
        "landing_contact_id": int(body.landing_contact_id),
        "crm_opportunity_id": int(body.crm_opportunity_id),
    }


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
    username: str = _facade().Field(..., min_length=1, max_length=64)
    new_password: str = _facade().Field(..., min_length=6, max_length=128)


class ProfileUpdateDTO(_facade().BaseModel):
    username: str = _facade().Field(..., min_length=2, max_length=64)


class PasswordChangeDTO(_facade().BaseModel):
    current_password: str = _facade().Field(..., min_length=1)
    new_password: str = _facade().Field(..., min_length=6, max_length=128)


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _delete_unused_verification_code(email: str, code: str) -> None:
    sf = _facade().get_session_factory()
    with sf() as session:
        session.query(_facade().VerificationCode).filter(
            _facade().VerificationCode.email == email,
            _facade().VerificationCode.code == code,
            _facade().VerificationCode.used.is_(False),
        ).delete(synchronize_session=False)
        session.commit()


def _background_send_verification_email(email: str, code: str, purpose: str) -> None:
    try:
        _facade().send_verification_email(email, code, purpose)
    except RECOVERABLE_ERRORS:
        _facade().logging.exception(
            "Background verification email failed email=%s purpose=%s", email, purpose
        )
        try:
            _facade()._delete_unused_verification_code(email, code)
        except RECOVERABLE_ERRORS:
            _facade().logging.exception("Failed to remove verification code after email failure")


def _verify_and_consume_verification_code(email: str, code: str) -> None:
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
