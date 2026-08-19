# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


def _fhd_cs_bridge_base() -> str:
    return (
        (
            _facade().os.environ.get("XCAGI_FHD_INTERNAL_URL")
            or _facade().os.environ.get("FHD_INTERNAL_BASE_URL")
            or _facade().os.environ.get("XCAGI_API_BASE_URL")
            or ""
        )
        .strip()
        .rstrip("/")
    )


def _cs_bridge_mod_id() -> str:
    return (
        _facade().os.environ.get("XCAGI_CS_BRIDGE_MOD_ID") or "xcagi-customer-service-bridge"
    ).strip()


def _default_cs_intake_webhook_url() -> str:
    explicit = (_facade().os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    base = _facade()._fhd_cs_bridge_base()
    return (
        f"{base}/api/mod/{_facade()._cs_bridge_mod_id()}/user-cs/demand-form/sync" if base else ""
    )


def _default_landing_funnel_webhook_url() -> str:
    explicit = (_facade().os.environ.get("XCAGI_LANDING_FUNNEL_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    base = _facade()._fhd_cs_bridge_base()
    return (
        f"{base}/api/mod/{_facade()._cs_bridge_mod_id()}/user-cs/landing-funnel/sync"
        if base
        else ""
    )


def _resolve_market_user_id_by_email(email: str) -> int | None:
    """已注册邮箱 → 自动关联 CRM / Pipeline（无需 cs_intake 签名链接）。"""
    em = (email or "").strip().casefold()
    if not em or "@" not in em:
        return None
    sf = _facade().get_session_factory()
    try:
        with sf() as session:
            row = (
                session.query(_facade().User)
                .filter(_facade().func.lower(_facade().User.email) == em)
                .filter(_facade().User.deleted_at.is_(None))
                .order_by(_facade().User.id.desc())
                .first()
            )
            if row:
                return int(row.id)
    except Exception:
        _facade().logger.debug("resolve market user by email failed", exc_info=True)
    return None


def _notify_cs_intake_webhook(payload: dict) -> None:
    uid = int(payload.get("market_user_id") or 0)
    url = (
        _facade()._default_cs_intake_webhook_url()
        if uid > 0
        else _facade()._default_landing_funnel_webhook_url()
    )
    if not url:
        _facade().logger.error(
            "cs intake webhook is not configured; contact was stored but not forwarded"
        )
        return
    secret = (
        _facade().os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_SECRET")
        or _facade().os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Intake-Webhook-Secret"] = secret
    try:
        from modstore_server.cs_webhook_outbox import deliver_webhook_with_retry

        deliver_webhook_with_retry(target_url=url, payload=payload, headers=headers)
    except Exception:
        _facade().logger.exception("cs intake webhook notify failed")


def _require_internal_api_key(request: _facade().Request) -> None:
    expected = (
        _facade().os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or _facade().os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    if not expected:
        raise _facade().HTTPException(status_code=503, detail="internal api not configured")
    got = (request.headers.get("x-internal-api-key") or "").strip()
    if not got or not _facade().secrets.compare_digest(got, expected):
        raise _facade().HTTPException(status_code=403, detail="invalid internal api key")


@_facade().router.post("/public/contact", summary="落地页联系表单（匿名，入库）", tags=["market"])
def api_public_contact_submit(
    body: _facade().PublicContactDTO,
    request: _facade().Request,
    background_tasks: _facade().BackgroundTasks,
):
    from modstore_server.market_shared import _CONTACT_EMAIL_RE

    email = (body.email or "").strip()
    if not _CONTACT_EMAIL_RE.match(email):
        raise _facade().HTTPException(status_code=400, detail="邮箱格式不正确")
    if not body.privacy_agreed:
        raise _facade().HTTPException(status_code=400, detail="请先阅读并同意用户协议与隐私政策")
    _facade()._public_contact_rate_allow(_facade()._public_contact_client_key(request))
    submitted_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    privacy_version = (body.privacy_version or _facade().CONTACT_PRIVACY_VERSION).strip()[:32]
    privacy_url = (body.privacy_url or _facade().CONTACT_PRIVACY_URL).strip()[:256]
    meta = {
        "user_agent": (request.headers.get("user-agent") or "")[:512],
        "referer": (request.headers.get("referer") or "")[:512],
        "privacy_agreed": True,
        "privacy_version": privacy_version,
        "privacy_url": privacy_url,
        "privacy_agreed_at": submitted_at,
    }
    desktop_os = _facade()._norm_os(body.desktop_os)
    if desktop_os:
        meta["desktop_os"] = desktop_os
    meta["need_mobile"] = bool(body.need_mobile)
    source = (body.source or "home").strip()[:64] or "home"
    tracking = _facade().normalize_contact_tracking_fields(body.campaign, body.medium, body.content)
    meta.update({k: v for (k, v) in tracking.items() if v})
    market_user_id: int | None = None
    try:
        from modstore_server.cs_intake_link import verify_cs_intake_token as _verify_cs
    except ModuleNotFoundError:
        _verify_cs = None
    if body.cs_uid and body.cs_t and _verify_cs and _verify_cs(int(body.cs_uid), body.cs_t):
        market_user_id = int(body.cs_uid)
        source = "cs_intake"
        meta["market_user_id"] = market_user_id
    row = _facade().LandingContactSubmission(
        name=(body.name or "").strip()[:128],
        email=email[:256],
        phone=(body.phone or "").strip()[:64],
        company=(body.company or "").strip()[:256],
        message=(body.message or "").strip()[:8000],
        source=source,
        meta_json=_facade().json.dumps(meta, ensure_ascii=False),
    )
    sf = _facade().get_session_factory()
    try:
        with sf() as session:
            session.add(row)
            session.commit()
            new_id = row.id
    except _facade().SQLAlchemyError as exc:
        _facade().logger.exception("public contact submit failed")
        raise _facade().HTTPException(
            status_code=503, detail="提交服务暂不可用，请稍后重试"
        ) from exc
    audit_code = _facade()._format_contact_audit_code(new_id)
    if not market_user_id:
        resolved = _facade()._resolve_market_user_id_by_email(email)
        if resolved:
            market_user_id = resolved
            meta["market_user_id"] = market_user_id
            try:
                with sf() as session:
                    row2 = session.get(_facade().LandingContactSubmission, new_id)
                    if row2:
                        row2.meta_json = _facade().json.dumps(meta, ensure_ascii=False)
                        session.commit()
            except _facade().SQLAlchemyError:
                _facade().logger.debug("bind market_user_id to landing meta failed", exc_info=True)
    webhook_payload = {
        "market_user_id": market_user_id,
        "landing_contact_id": new_id,
        "audit_code": audit_code,
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "company": row.company,
        "message": row.message,
        "submitted_at": submitted_at,
        "intake_source": source,
        **tracking,
        "desktop_os": desktop_os or None,
        "need_mobile": bool(body.need_mobile),
        "privacy_agreed": True,
        "privacy_version": privacy_version,
        "privacy_url": privacy_url,
        "privacy_agreed_at": submitted_at,
    }
    background_tasks.add_task(_facade()._notify_cs_intake_webhook, webhook_payload)
    return {"ok": True, "id": new_id, "audit_code": audit_code}


@_facade().router.get(
    "/public/contact/companies/match",
    summary="联系页 · 公司名称匹配（自有库建议 + 百度/企查查式联网必选）",
    tags=["market"],
)
async def api_public_contact_company_match(
    request: _facade().Request,
    q: str = _facade().Query("", max_length=80),
    limit: int = _facade().Query(8, ge=1, le=20),
    web: bool = _facade().Query(True, description="无自有库命中时用爬虫+Tavily 检索公司名"),
):
    query = (q or "").strip()
    if len(query) < 2:
        return {"ok": True, "query": query, "matched": None, "suggestions": [], "found": False}
    _facade()._public_contact_company_match_rate_allow(
        _facade()._public_contact_client_key(request)
    )
    return await _facade().build_company_match_payload(query, limit, web)


@_facade().router.get(
    "/market/workbench/companies/match", summary="工作台 · 公司名称联网匹配", tags=["market"]
)
async def api_workbench_company_match(
    request: _facade().Request,
    q: str = _facade().Query("", max_length=80),
    limit: int = _facade().Query(8, ge=1, le=20),
    web: bool = _facade().Query(True, description="无自有库命中时用爬虫+Tavily 检索公司名"),
    user: _facade().Optional[_facade().User] = _facade().Depends(_facade()._optional_current_user),
):
    query = (q or "").strip()
    if len(query) < 2:
        return {"ok": True, "query": query, "matched": None, "suggestions": [], "found": False}
    rate_key = f"user:{int(user.id)}" if user else _facade()._public_contact_client_key(request)
    _facade()._workbench_company_match_rate_allow(rate_key)
    return await _facade().build_company_match_payload(query, limit, web)


@_facade().router.get(
    "/internal/payment/summary",
    summary="客服 · 按用户核对市场支付订单（服务间，Java/JSON SoT）",
    tags=["market"],
)
def api_internal_payment_summary(
    request: _facade().Request,
    market_user_id: int = _facade().Query(..., gt=0),
    min_amount_cents: int | None = _facade().Query(None, ge=0),
    expected_out_trade_no: str = _facade().Query("", max_length=64),
):
    _facade()._require_internal_api_key(request)
    from modstore_server.payment_cs_internal import payment_summary_for_cs

    return {
        "ok": True,
        **payment_summary_for_cs(
            int(market_user_id),
            min_amount_cents=min_amount_cents,
            expected_out_trade_no=(expected_out_trade_no or "").strip(),
        ),
    }


@_facade().router.get(
    "/internal/cs-intake/latest", summary="客服需求采集最新提交（服务间）", tags=["market"]
)
def api_internal_cs_intake_latest(market_user_id: int, request: _facade().Request):
    _facade()._require_internal_api_key(request)
    uid = int(market_user_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().LandingContactSubmission)
            .filter(_facade().LandingContactSubmission.source == "cs_intake")
            .order_by(_facade().LandingContactSubmission.created_at.desc())
            .limit(300)
            .all()
        )
        for row in rows:
            try:
                meta = _facade().json.loads(row.meta_json or "{}")
            except _facade().json.JSONDecodeError:
                meta = {}
            if int(meta.get("market_user_id") or 0) != uid:
                continue
            payload = _facade()._landing_submission_payload(row)
            payload["market_user_id"] = uid
            return {"ok": True, "submission": payload}
    return {"ok": True, "submission": None}


@_facade().router.get(
    "/internal/contact/by-audit-code",
    summary="客服 · 按审核码查询/绑定官网需求单（服务间）",
    tags=["market"],
)
def api_internal_contact_by_audit_code(
    request: _facade().Request,
    code: str = _facade().Query(..., min_length=1, max_length=32),
    market_user_id: int | None = _facade().Query(None, gt=0),
    bind: bool = _facade().Query(
        True, description="true=绑定到 market_user_id；false=仅查询表单内容"
    ),
):
    _facade()._require_internal_api_key(request)
    sid = _facade().parse_contact_audit_code(code)
    if not sid:
        raise _facade().HTTPException(
            status_code=400, detail="审核码格式不正确，请填写如 XC-000123"
        )
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.get(_facade().LandingContactSubmission, sid)
        if not row:
            raise _facade().HTTPException(status_code=404, detail="未找到该审核码对应的需求单")
        try:
            meta = _facade().json.loads(row.meta_json or "{}")
        except _facade().json.JSONDecodeError:
            meta = {}
        if market_user_id:
            bound = int(meta.get("market_user_id") or 0)
            uid = int(market_user_id)
            if bound and bound != uid:
                raise _facade().HTTPException(
                    status_code=409, detail="该审核码已绑定其他客户，请核对后联系管理员"
                )
            if bind and (not bound):
                meta["market_user_id"] = uid
                meta["redeemed_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
                row.meta_json = _facade().json.dumps(meta, ensure_ascii=False)
                session.commit()
        return {"ok": True, "submission": _facade()._landing_submission_payload(row)}


class EnsureEnterpriseProfileDTO(_facade().BaseModel):
    market_user_id: int = _facade().Field(..., gt=0)
    company: str = _facade().Field(default="", max_length=256)
    display_name: str = _facade().Field(default="", max_length=64)
    mod_ids: list[str] = _facade().Field(default_factory=list)


@_facade().router.post(
    "/internal/cs-intake/ensure-enterprise-profile",
    summary="客服 · 表单入库后设为企业客户并同步显示名（服务间）",
    tags=["market"],
)
def api_internal_cs_intake_ensure_enterprise_profile(
    request: _facade().Request, body: EnsureEnterpriseProfileDTO
):
    _facade()._require_internal_api_key(request)
    uid = int(body.market_user_id)
    try:
        requested_mod_ids = _facade().normalize_enterprise_entitlement_mod_ids(body.mod_ids)
    except ValueError as exc:
        raise _facade().HTTPException(status_code=400, detail=str(exc)) from exc
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == uid).first()
        if not target:
            raise _facade().HTTPException(status_code=404, detail="用户不存在")
        desired = (body.display_name or body.company or "").strip()[:64]
        if not desired:
            desired = str(target.username or "").strip()[:64]
        renamed = False
        if desired and desired != target.username:
            conflict = (
                session.query(_facade().User)
                .filter(_facade().User.username == desired, _facade().User.id != uid)
                .first()
            )
            if conflict:
                suffix = f"-{uid}"
                desired = f"{desired[:max(1, 64 - len(suffix))]}{suffix}"
            target.username = desired
            renamed = True
        if not target.is_enterprise:
            target.is_enterprise = True
        added_mod_ids: list[str] = []
        if requested_mod_ids:
            from modstore_server.db.catalog import UserMod

            existing = {
                str(row[0])
                for row in session.query(UserMod.mod_id)
                .filter(UserMod.user_id == uid, UserMod.mod_id.in_(requested_mod_ids))
                .all()
            }
            for mod_id in requested_mod_ids:
                if mod_id in existing:
                    continue
                session.add(UserMod(user_id=uid, mod_id=mod_id))
                existing.add(mod_id)
                added_mod_ids.append(mod_id)
        session.commit()
        return {
            "ok": True,
            "skipped": False,
            "user_id": uid,
            "username": target.username,
            "is_enterprise": bool(target.is_enterprise),
            "renamed": renamed,
            "mod_ids": requested_mod_ids,
            "added_mod_ids": added_mod_ids,
        }


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
    except Exception:
        _facade().logging.exception(
            "Background verification email failed email=%s purpose=%s", email, purpose
        )
        try:
            _facade()._delete_unused_verification_code(email, code)
        except Exception:
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
