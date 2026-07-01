"""XC AGI 在线市场 API：认证、注册、登录、公开联系表单。"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from modstore_server import account_level_service
from modstore_server.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_by_id,
    hash_password,
    register_user,
    verify_password,
)
from modstore_server.digest_identity import normalize_digest_identity_code, verify_digest_identity
from modstore_server.digest_identity_peer_api import call_upstream_digest_verify
from modstore_server.email_service import (
    assert_email_outbound_configured,
    find_user_by_email,
    generate_verification_code,
    send_verification_email,
)
from modstore_server.enterprise_entitlements import normalize_enterprise_entitlement_mod_ids
from modstore_server.java_me_profile import fetch_java_user_overlay
from modstore_server.market_shared import (
    _get_current_user,
    _optional_current_user,
    _public_contact_client_key,
    _public_contact_company_match_rate_allow,
    _public_contact_rate_allow,
    _require_admin,
    _workbench_company_match_rate_allow,
)
from modstore_server.models import (
    CatalogItem,
    LandingContactSubmission,
    User,
    VerificationCode,
    get_session_factory,
)
from modstore_server.research_tools import (
    is_plausible_company_name,
    sanitize_contact_company_web_error,
    search_company_names_via_web,
)
from modstore_server.user_avatar_service import (
    _MIME_BY_SUFFIX,
    avatar_path_column,
    avatar_version_column,
    delete_user_avatar_files,
    public_avatar_url_for_user,
    resolve_avatar_file,
    save_user_avatar,
)

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


class PublicContactDTO(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    email: str = Field(..., min_length=4, max_length=256)
    phone: str = Field("", max_length=64)
    company: str = Field("", max_length=256)
    message: str = Field("", max_length=8000)
    source: str = Field("home", max_length=64)
    desktop_os: str = Field(
        default="",
        max_length=16,
        description="客户桌面系统：mac 或 win，用于交付对应安装包",
    )
    need_mobile: bool = Field(
        default=True,
        description="是否同时需要 Android 手机端安装包",
    )
    cs_uid: int | None = Field(default=None, gt=0)
    cs_t: str = Field(default="", max_length=512)


def _fhd_cs_bridge_base() -> str:
    return (
        (
            os.environ.get("XCAGI_FHD_INTERNAL_URL")
            or os.environ.get("FHD_INTERNAL_BASE_URL")
            or os.environ.get("XCAGI_API_BASE_URL")
            or "http://127.0.0.1:8765"
        )
        .strip()
        .rstrip("/")
    )


def _cs_bridge_mod_id() -> str:
    return (os.environ.get("XCAGI_CS_BRIDGE_MOD_ID") or "xcagi-customer-service-bridge").strip()


def _default_cs_intake_webhook_url() -> str:
    explicit = (os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    base = _fhd_cs_bridge_base()
    return f"{base}/api/mod/{_cs_bridge_mod_id()}/user-cs/demand-form/sync"


def _default_landing_funnel_webhook_url() -> str:
    explicit = (os.environ.get("XCAGI_LANDING_FUNNEL_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    base = _fhd_cs_bridge_base()
    return f"{base}/api/mod/{_cs_bridge_mod_id()}/user-cs/landing-funnel/sync"


def _resolve_market_user_id_by_email(email: str) -> int | None:
    """已注册邮箱 → 自动关联 CRM / Pipeline（无需 cs_intake 签名链接）。"""
    em = (email or "").strip().casefold()
    if not em or "@" not in em:
        return None
    sf = get_session_factory()
    try:
        with sf() as session:
            row = (
                session.query(User)
                .filter(func.lower(User.email) == em)
                .filter(User.deleted_at.is_(None))
                .order_by(User.id.desc())
                .first()
            )
            if row:
                return int(row.id)
    except Exception:
        logger.debug("resolve market user by email failed", exc_info=True)
    return None


def _notify_cs_intake_webhook(payload: dict) -> None:
    uid = int(payload.get("market_user_id") or 0)
    url = _default_cs_intake_webhook_url() if uid > 0 else _default_landing_funnel_webhook_url()
    if not url:
        return
    secret = (
        os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_SECRET")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Intake-Webhook-Secret"] = secret
    try:
        from modstore_server.cs_webhook_outbox import deliver_webhook_with_retry

        deliver_webhook_with_retry(target_url=url, payload=payload, headers=headers)
    except Exception:
        logger.exception("cs intake webhook notify failed")


_AUDIT_CODE_RE = re.compile(r"^XC-?0*(\d{1,8})$", re.IGNORECASE)


def _format_contact_audit_code(submission_id: int) -> str:
    """用户可见的需求单审核码（与入库 id 一一对应，便于客服查询）。"""
    sid = max(0, int(submission_id))
    return f"XC-{sid:06d}"


def parse_contact_audit_code(code: str) -> int | None:
    raw = re.sub(r"\s+", "", (code or "").strip().upper())
    if not raw:
        return None
    m = _AUDIT_CODE_RE.match(raw)
    if m:
        sid = int(m.group(1))
        return sid if sid > 0 else None
    if raw.isdigit():
        sid = int(raw)
        return sid if sid > 0 else None
    return None


def _normalize_desktop_os(value: str | None) -> str:
    raw = (value or "").strip().casefold()
    if raw in ("mac", "macos", "darwin", "osx"):
        return "mac"
    if raw in ("win", "windows", "win32", "pc"):
        return "win"
    return ""


def _landing_submission_payload(row: LandingContactSubmission) -> dict:
    try:
        meta = json.loads(row.meta_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    created = row.created_at
    submitted_at = created.isoformat() if created else ""
    desktop_os = _normalize_desktop_os(str(meta.get("desktop_os") or ""))
    need_mobile = meta.get("need_mobile")
    if need_mobile is None:
        need_mobile_val = True
    else:
        need_mobile_val = (
            bool(need_mobile)
            if isinstance(need_mobile, bool)
            else str(need_mobile).lower()
            not in (
                "0",
                "false",
                "no",
            )
        )
    return {
        "landing_contact_id": row.id,
        "audit_code": _format_contact_audit_code(row.id),
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "company": row.company,
        "message": row.message,
        "source": row.source,
        "desktop_os": desktop_os or None,
        "need_mobile": need_mobile_val,
        "market_user_id": int(meta.get("market_user_id") or 0) or None,
        "submitted_at": submitted_at,
        "created_at": submitted_at,
    }


def _require_internal_api_key(request: Request) -> None:
    expected = (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    if not expected:
        raise HTTPException(status_code=503, detail="internal api not configured")
    got = (request.headers.get("x-internal-api-key") or "").strip()
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail="invalid internal api key")


@router.post("/public/contact", summary="落地页联系表单（匿名，入库）", tags=["market"])
def api_public_contact_submit(
    body: PublicContactDTO,
    request: Request,
    background_tasks: BackgroundTasks,
):
    from modstore_server.market_shared import _CONTACT_EMAIL_RE

    email = (body.email or "").strip()
    if not _CONTACT_EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    _public_contact_rate_allow(_public_contact_client_key(request))
    meta = {
        "user_agent": (request.headers.get("user-agent") or "")[:512],
        "referer": (request.headers.get("referer") or "")[:512],
    }
    desktop_os = _normalize_desktop_os(body.desktop_os)
    if desktop_os:
        meta["desktop_os"] = desktop_os
    meta["need_mobile"] = bool(body.need_mobile)
    source = (body.source or "home").strip()[:64] or "home"
    market_user_id: int | None = None
    try:
        from modstore_server.cs_intake_link import verify_cs_intake_token as _verify_cs
    except ModuleNotFoundError:
        _verify_cs = None
    if body.cs_uid and body.cs_t and _verify_cs and _verify_cs(int(body.cs_uid), body.cs_t):
        market_user_id = int(body.cs_uid)
        source = "cs_intake"
        meta["market_user_id"] = market_user_id
    row = LandingContactSubmission(
        name=(body.name or "").strip()[:128],
        email=email[:256],
        phone=(body.phone or "").strip()[:64],
        company=(body.company or "").strip()[:256],
        message=(body.message or "").strip()[:8000],
        source=source,
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    sf = get_session_factory()
    try:
        with sf() as session:
            session.add(row)
            session.commit()
            new_id = row.id
    except SQLAlchemyError as exc:
        logger.exception("public contact submit failed")
        raise HTTPException(status_code=503, detail="提交服务暂不可用，请稍后重试") from exc
    audit_code = _format_contact_audit_code(new_id)
    if not market_user_id:
        resolved = _resolve_market_user_id_by_email(email)
        if resolved:
            market_user_id = resolved
            meta["market_user_id"] = market_user_id
            try:
                with sf() as session:
                    row2 = session.get(LandingContactSubmission, new_id)
                    if row2:
                        row2.meta_json = json.dumps(meta, ensure_ascii=False)
                        session.commit()
            except SQLAlchemyError:
                logger.debug("bind market_user_id to landing meta failed", exc_info=True)
    submitted_at = datetime.now(timezone.utc).isoformat()
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
        "desktop_os": desktop_os or None,
        "need_mobile": bool(body.need_mobile),
    }
    background_tasks.add_task(_notify_cs_intake_webhook, webhook_payload)
    return {"ok": True, "id": new_id, "audit_code": audit_code}


def _normalize_company_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().casefold())


def _company_match_score(query: str, candidate: str) -> int:
    q = _normalize_company_key(query)
    c = _normalize_company_key(candidate)
    if not q or not c:
        return -1
    if q == c:
        return 100
    if c.startswith(q) or q.startswith(c):
        return 85
    if q in c or c in q:
        return 70
    return -1


def _iter_company_match_db_paths() -> list[Path]:
    paths: list[Path] = []
    raw = (os.environ.get("XCAGI_COMPANY_MATCH_DB_PATHS") or "").strip()
    if raw:
        for part in raw.split(","):
            p = Path(part.strip()).expanduser()
            if str(p):
                paths.append(p)
    repo = Path(os.environ.get("MODSTORE_REPO_ROOT", "/root/成都修茈科技有限公司")).expanduser()
    paths.extend(
        [
            repo / "data" / "mod_dbs" / "taiyangniao_pro.db",
            Path("/root/data/mod_dbs/taiyangniao_pro.db"),
            repo / "mods" / "taiyangniao-pro" / "mod_dbs" / "taiyangniao_pro.db",
            Path("/opt/fhd-full/data/mod_dbs/taiyangniao_pro.db"),
            Path("/opt/fhd-full/XCAGI/data/mod_dbs/taiyangniao_pro.db"),
        ]
    )
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _erp_company_names(query: str, limit: int) -> list[str]:
    import sqlite3

    pattern = f"%{query.strip()}%"
    names: list[str] = []
    for db_path in _iter_company_match_db_paths():
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            cur = conn.execute(
                "SELECT DISTINCT customer_name FROM customers "
                "WHERE customer_name != '' AND customer_name LIKE ? COLLATE NOCASE "
                "ORDER BY LENGTH(customer_name) ASC LIMIT ?",
                (pattern, limit),
            )
            for row in cur.fetchall():
                val = (row[0] or "").strip()
                if val and val not in names:
                    names.append(val)
            conn.close()
            if names:
                break
        except Exception:
            logger.debug("erp company match skipped for %s", db_path, exc_info=True)
    return names[:limit]


def _submission_company_rows(
    session, query: str, limit: int
) -> list[tuple[str, int, datetime | None]]:
    pattern = f"%{query.strip()}%"
    rows = (
        session.query(
            LandingContactSubmission.company,
            func.count(LandingContactSubmission.id).label("cnt"),
            func.max(LandingContactSubmission.created_at).label("last_at"),
        )
        .filter(
            LandingContactSubmission.company != "",
            LandingContactSubmission.company.ilike(pattern),
        )
        .group_by(LandingContactSubmission.company)
        .order_by(func.count(LandingContactSubmission.id).desc())
        .limit(limit)
        .all()
    )
    return [
        (str(name or "").strip(), int(cnt or 0), last_at)
        for name, cnt, last_at in rows
        if str(name or "").strip()
    ]


async def _company_match_payload(query: str, limit: int, web: bool) -> dict:
    by_name: dict[str, dict] = {}
    typed_exact = is_plausible_company_name(query)
    sf = get_session_factory()
    try:
        with sf() as session:
            for name, cnt, last_at in _submission_company_rows(session, query, limit=40):
                by_name[name] = {
                    "name": name,
                    "exact": _normalize_company_key(name) == _normalize_company_key(query),
                    "has_history": True,
                    "submission_count": cnt,
                    "in_crm": False,
                    "source": "submission",
                    "last_submitted_at": last_at.isoformat() if last_at else None,
                    "_score": _company_match_score(query, name),
                }
    except (ProgrammingError, SQLAlchemyError) as exc:
        logger.warning("company match: landing_contact_submissions query skipped: %s", exc)

    for name in _erp_company_names(query, limit=20):
        score = _company_match_score(query, name)
        if score < 0:
            continue
        existing = by_name.get(name)
        if existing:
            existing["in_crm"] = True
            existing["source"] = "both"
            existing["_score"] = max(int(existing.get("_score") or 0), score)
        else:
            by_name[name] = {
                "name": name,
                "exact": _normalize_company_key(name) == _normalize_company_key(query),
                "has_history": False,
                "submission_count": 0,
                "in_crm": True,
                "source": "erp",
                "last_submitted_at": None,
                "_score": score,
            }

    web_used = False
    web_error: str | None = None
    web_via = ""
    incomplete_query = len(query) >= 2 and not typed_exact
    if web:
        try:
            web_names, web_error, web_via = await search_company_names_via_web(
                query, max_results=limit
            )
            if web_names:
                web_used = True
            for name in web_names:
                if not is_plausible_company_name(name):
                    continue
                score = _company_match_score(query, name)
                if score < 60:
                    score = 70
                existing = by_name.get(name)
                by_name[name] = {
                    "name": name,
                    "exact": _normalize_company_key(name) == _normalize_company_key(query),
                    "has_history": bool(existing and existing.get("has_history")),
                    "submission_count": int((existing or {}).get("submission_count") or 0),
                    "in_crm": bool(existing and existing.get("in_crm")),
                    "in_web": True,
                    "source": "web",
                    "last_submitted_at": (existing or {}).get("last_submitted_at"),
                    "_score": max(int((existing or {}).get("_score") or 0), score),
                }
        except Exception as exc:
            logger.warning("company match web search failed: %s", exc)
            web_error = "联网检索暂时不可用"
    web_error = sanitize_contact_company_web_error(web_error)

    ranked = sorted(
        by_name.values(),
        key=lambda item: (
            1 if item.get("source") == "web" else 0,
            int(item.get("_score") or 0),
            int(item.get("submission_count") or 0),
            len(item.get("name") or ""),
        ),
        reverse=True,
    )
    suggestions: list[dict] = []
    matched = None
    for item in ranked:
        score = int(item.get("_score") or 0)
        payload = {k: v for k, v in item.items() if k != "_score"}
        if score < 60:
            continue
        is_web = payload.get("source") == "web"
        if web and not is_web:
            if len(suggestions) < limit:
                suggestions.append(payload)
            continue
        if matched is None and (not web or is_web):
            matched = payload
        if len(suggestions) < limit:
            suggestions.append(payload)

    found = bool(matched) if web else bool(matched or suggestions)
    return {
        "ok": True,
        "query": query,
        "found": found,
        "matched": matched,
        "suggestions": suggestions,
        "web_used": web_used,
        "web_error": web_error,
        "web_via": web_via or None,
        "query_incomplete": bool(incomplete_query and not found and not web_used),
    }


@router.get(
    "/public/contact/companies/match",
    summary="联系页 · 公司名称匹配（自有库建议 + 百度/企查查式联网必选）",
    tags=["market"],
)
async def api_public_contact_company_match(
    request: Request,
    q: str = Query("", max_length=80),
    limit: int = Query(8, ge=1, le=20),
    web: bool = Query(True, description="无自有库命中时用爬虫+Tavily 检索公司名"),
):
    query = (q or "").strip()
    if len(query) < 2:
        return {"ok": True, "query": query, "matched": None, "suggestions": [], "found": False}
    _public_contact_company_match_rate_allow(_public_contact_client_key(request))
    return await _company_match_payload(query, limit, web)


@router.get(
    "/market/workbench/companies/match",
    summary="工作台 · 公司名称联网匹配",
    tags=["market"],
)
async def api_workbench_company_match(
    request: Request,
    q: str = Query("", max_length=80),
    limit: int = Query(8, ge=1, le=20),
    web: bool = Query(True, description="无自有库命中时用爬虫+Tavily 检索公司名"),
    user: Optional[User] = Depends(_optional_current_user),
):
    query = (q or "").strip()
    if len(query) < 2:
        return {"ok": True, "query": query, "matched": None, "suggestions": [], "found": False}
    rate_key = f"user:{int(user.id)}" if user else _public_contact_client_key(request)
    _workbench_company_match_rate_allow(rate_key)
    return await _company_match_payload(query, limit, web)


@router.get(
    "/internal/payment/summary",
    summary="客服 · 按用户核对市场支付订单（服务间，Java/JSON SoT）",
    tags=["market"],
)
def api_internal_payment_summary(
    request: Request,
    market_user_id: int = Query(..., gt=0),
    min_amount_cents: int | None = Query(None, ge=0),
    expected_out_trade_no: str = Query("", max_length=64),
):
    _require_internal_api_key(request)
    from modstore_server.payment_cs_internal import payment_summary_for_cs

    return {
        "ok": True,
        **payment_summary_for_cs(
            int(market_user_id),
            min_amount_cents=min_amount_cents,
            expected_out_trade_no=(expected_out_trade_no or "").strip(),
        ),
    }


@router.get("/internal/cs-intake/latest", summary="客服需求采集最新提交（服务间）", tags=["market"])
def api_internal_cs_intake_latest(market_user_id: int, request: Request):
    _require_internal_api_key(request)
    uid = int(market_user_id)
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(LandingContactSubmission)
            .filter(LandingContactSubmission.source == "cs_intake")
            .order_by(LandingContactSubmission.created_at.desc())
            .limit(300)
            .all()
        )
        for row in rows:
            try:
                meta = json.loads(row.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            if int(meta.get("market_user_id") or 0) != uid:
                continue
            payload = _landing_submission_payload(row)
            payload["market_user_id"] = uid
            return {"ok": True, "submission": payload}
    return {"ok": True, "submission": None}


@router.get(
    "/internal/contact/by-audit-code",
    summary="客服 · 按审核码查询/绑定官网需求单（服务间）",
    tags=["market"],
)
def api_internal_contact_by_audit_code(
    request: Request,
    code: str = Query(..., min_length=1, max_length=32),
    market_user_id: int | None = Query(None, gt=0),
    bind: bool = Query(
        True,
        description="true=绑定到 market_user_id；false=仅查询表单内容",
    ),
):
    _require_internal_api_key(request)
    sid = parse_contact_audit_code(code)
    if not sid:
        raise HTTPException(status_code=400, detail="审核码格式不正确，请填写如 XC-000123")
    sf = get_session_factory()
    with sf() as session:
        row = session.get(LandingContactSubmission, sid)
        if not row:
            raise HTTPException(status_code=404, detail="未找到该审核码对应的需求单")
        try:
            meta = json.loads(row.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if market_user_id:
            bound = int(meta.get("market_user_id") or 0)
            uid = int(market_user_id)
            if bound and bound != uid:
                raise HTTPException(
                    status_code=409,
                    detail="该审核码已绑定其他客户，请核对后联系管理员",
                )
            if bind and not bound:
                meta["market_user_id"] = uid
                meta["redeemed_at"] = datetime.now(timezone.utc).isoformat()
                row.meta_json = json.dumps(meta, ensure_ascii=False)
                session.commit()
        return {"ok": True, "submission": _landing_submission_payload(row)}


class EnsureEnterpriseProfileDTO(BaseModel):
    market_user_id: int = Field(..., gt=0)
    company: str = Field(default="", max_length=256)
    display_name: str = Field(default="", max_length=64)
    mod_ids: list[str] = Field(default_factory=list)


@router.post(
    "/internal/cs-intake/ensure-enterprise-profile",
    summary="客服 · 表单入库后设为企业客户并同步显示名（服务间）",
    tags=["market"],
)
def api_internal_cs_intake_ensure_enterprise_profile(
    request: Request,
    body: EnsureEnterpriseProfileDTO,
):
    _require_internal_api_key(request)
    uid = int(body.market_user_id)
    try:
        requested_mod_ids = normalize_enterprise_entitlement_mod_ids(body.mod_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sf = get_session_factory()
    with sf() as session:
        target = session.query(User).filter(User.id == uid).first()
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        desired = (body.display_name or body.company or "").strip()[:64]
        if not desired:
            desired = str(target.username or "").strip()[:64]
        renamed = False
        if desired and desired != target.username:
            conflict = session.query(User).filter(User.username == desired, User.id != uid).first()
            if conflict:
                suffix = f"-{uid}"
                desired = f"{desired[: max(1, 64 - len(suffix))]}{suffix}"
            target.username = desired
            renamed = True
        if not target.is_enterprise:
            target.is_enterprise = True
        added_mod_ids: list[str] = []
        if requested_mod_ids:
            from modstore_server.models_catalog import UserMod

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


@router.get(
    "/internal/cs-intake/enterprise-account",
    summary="客服 · 查询企业客户登录账号（服务间，不含密码明文）",
    tags=["market"],
)
def api_internal_cs_intake_enterprise_account(
    request: Request,
    market_user_id: int = Query(..., gt=0),
):
    _require_internal_api_key(request)
    uid = int(market_user_id)
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == uid).first()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            raise HTTPException(status_code=404, detail="用户已注销")
        return {
            "ok": True,
            "user_id": uid,
            "username": str(row.username or "").strip(),
            "email": str(row.email or "").strip(),
            "is_enterprise": bool(getattr(row, "is_enterprise", False)),
        }


class IssueEnterprisePasswordDTO(BaseModel):
    market_user_id: int = Field(..., gt=0)
    password: str = Field(..., min_length=8, max_length=128)


@router.post(
    "/internal/cs-intake/issue-enterprise-password",
    summary="客服 · 重置企业客户修茈市场登录密码（服务间）",
    tags=["market"],
)
def api_internal_cs_intake_issue_enterprise_password(
    request: Request,
    body: IssueEnterprisePasswordDTO,
):
    _require_internal_api_key(request)
    uid = int(body.market_user_id)
    plain = (body.password or "").strip()
    if len(plain) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == uid).first()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            raise HTTPException(status_code=404, detail="用户已注销")
        row.password_hash = hash_password(plain)
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


class LinkCrmDTO(BaseModel):
    landing_contact_id: int = Field(..., gt=0)
    crm_opportunity_id: int = Field(..., gt=0)
    market_user_id: int | None = Field(default=None, gt=0)


@router.post(
    "/internal/contact/link-crm",
    summary="客服 · 回写 landing 联系记录与 CRM 商机关联（服务间）",
    tags=["market"],
)
def api_internal_contact_link_crm(request: Request, body: LinkCrmDTO):
    _require_internal_api_key(request)
    sf = get_session_factory()
    with sf() as session:
        row = session.get(LandingContactSubmission, int(body.landing_contact_id))
        if not row:
            raise HTTPException(status_code=404, detail="未找到该联系表单记录")
        try:
            meta = json.loads(row.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if body.market_user_id:
            bound = int(meta.get("market_user_id") or 0)
            uid = int(body.market_user_id)
            if bound and bound != uid:
                raise HTTPException(status_code=409, detail="market_user_id 与记录不一致")
            meta["market_user_id"] = uid
        meta["crm_opportunity_id"] = int(body.crm_opportunity_id)
        meta["crm_linked_at"] = datetime.now(timezone.utc).isoformat()
        row.meta_json = json.dumps(meta, ensure_ascii=False)
        session.commit()
    return {
        "ok": True,
        "landing_contact_id": int(body.landing_contact_id),
        "crm_opportunity_id": int(body.crm_opportunity_id),
    }


class RegisterDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6)
    email: str = Field(..., min_length=5, max_length=128, description="必填，用于接收验证码")
    verification_code: str = Field(..., min_length=4, max_length=16, description="邮箱验证码")


class LoginDTO(BaseModel):
    username: str
    password: str


class SendCodeDTO(BaseModel):
    email: str


class LoginWithCodeDTO(BaseModel):
    email: str
    code: str


class RefreshTokenDTO(BaseModel):
    refresh_token: str


class ResetPasswordDTO(BaseModel):
    email: str
    code: str = Field(..., min_length=4, max_length=16)
    new_password: str = Field(..., min_length=6, max_length=128)


class AdminResetUserPasswordDTO(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., min_length=6, max_length=128)


class ProfileUpdateDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)


class PasswordChangeDTO(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _delete_unused_verification_code(email: str, code: str) -> None:
    sf = get_session_factory()
    with sf() as session:
        session.query(VerificationCode).filter(
            VerificationCode.email == email,
            VerificationCode.code == code,
            VerificationCode.used == False,
        ).delete(synchronize_session=False)
        session.commit()


def _background_send_verification_email(email: str, code: str, purpose: str) -> None:
    try:
        send_verification_email(email, code, purpose)
    except Exception:
        logging.exception(
            "Background verification email failed email=%s purpose=%s",
            email,
            purpose,
        )
        try:
            _delete_unused_verification_code(email, code)
        except Exception:
            logging.exception("Failed to remove verification code after email failure")


def _verify_and_consume_verification_code(email: str, code: str) -> None:
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "请填写验证码")
    sf = get_session_factory()
    with sf() as session:
        vc = (
            session.query(VerificationCode)
            .filter(
                VerificationCode.email == email,
                VerificationCode.code == code,
                VerificationCode.used == False,
                VerificationCode.expires_at > datetime.now(timezone.utc),
            )
            .order_by(VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise HTTPException(401, "验证码无效或已过期")
        vc.used = True
        session.commit()


@router.post("/auth/register", summary="注册用户（邮箱验证码通过 send-register-code）")
def api_register(body: RegisterDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm or "@" not in email_norm:
        raise HTTPException(400, "请填写有效邮箱")
    vcode = (body.verification_code or "").strip()
    if not vcode:
        raise HTTPException(400, "请填写邮箱验证码，并先通过「获取验证码」收取邮件")
    _verify_and_consume_verification_code(email_norm, vcode)
    try:
        user = register_user(body.username, body.password, email_norm)
    except ValueError as e:
        raise HTTPException(409, str(e))
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
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


@router.post("/auth/login", summary="用户名密码登录，返回 JWT")
def api_login(body: LoginDTO):
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
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


class InternalSsoIssueTokenDTO(BaseModel):
    username: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    oidc_sub: str = Field(default="", max_length=256)
    display_name: str = Field(default="", max_length=128)


@router.post("/auth/internal/sso-issue-token", include_in_schema=False)
def api_internal_sso_issue_token(body: InternalSsoIssueTokenDTO, request: Request):
    """FHD OIDC 回调后签发 MODstore JWT（Header: X-Internal-Api-Key）。"""
    _require_internal_api_key(request)
    from modstore_server.auth_service import issue_market_tokens_for_sso_identity

    try:
        data = issue_market_tokens_for_sso_identity(
            username=(body.username or "").strip(),
            email=(body.email or "").strip(),
            oidc_sub=(body.oidc_sub or "").strip(),
            display_name=(body.display_name or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": data}


@router.get("/auth/me", summary="当前用户资料与等级（含 Java 侧叠加字段）")
def api_me(request: Request, user: Optional[User] = Depends(_optional_current_user)):
    # 与 FHD /api/auth/me 一致：未登录用 200，避免 SPA 控制台刷 401。
    if not user:
        return {"ok": False, "success": False, "error": "请先登录"}
    exp = int(getattr(user, "experience", 0) or 0)
    level_profile = account_level_service.build_level_profile(exp).to_dict()
    phone_out = (getattr(user, "phone", None) or "") or ""
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    overlay = fetch_java_user_overlay(auth_header, expect_user_id=int(user.id))
    if overlay is not None:
        exp = int(overlay.experience)
        if isinstance(overlay.level_profile, dict) and overlay.level_profile:
            level_profile = overlay.level_profile
        else:
            level_profile = account_level_service.build_level_profile(exp).to_dict()
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
        "avatar_url": public_avatar_url_for_user(user),
    }


@router.post("/auth/avatar", summary="上传或更换当前用户头像")
async def api_upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(_get_current_user),
):
    payload = await file.read()
    relpath, _mime = save_user_avatar(int(user.id), payload, file.filename or "avatar.jpg")
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.avatar_path = relpath
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
        version = int(row.avatar_version)
        url = public_avatar_url_for_user(row)
    return {"ok": True, "avatar_url": url, "avatar_version": version}


@router.delete("/auth/avatar", summary="移除当前用户头像")
def api_delete_avatar(user: User = Depends(_get_current_user)):
    delete_user_avatar_files(int(user.id))
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.avatar_path = ""
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
    return {"ok": True, "avatar_url": None}


@router.get("/auth/avatar/file", summary="读取当前用户头像（需登录）")
def api_avatar_file(
    user: User = Depends(_get_current_user),
    v: Optional[int] = Query(None, description="与 avatar_url 中 v 一致，仅用于缓存校验"),
):
    rel = avatar_path_column(user)
    if not rel:
        raise HTTPException(404, "未设置头像")
    if v is not None and int(v) != avatar_version_column(user):
        raise HTTPException(404, "头像已更新，请刷新")
    path = resolve_avatar_file(rel)
    if not path.is_file():
        raise HTTPException(404, "头像文件不存在")
    suffix = path.suffix.lower()
    media = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=f"avatar{suffix}")


@router.post("/auth/send-code", status_code=202, summary="向已注册邮箱发送登录验证码")
def api_send_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    user = find_user_by_email(email_norm)
    if not user:
        raise HTTPException(404, "该邮箱未注册")

    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "login")

    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@router.post("/auth/send-register-code", status_code=202, summary="向新邮箱发送注册验证码")
def api_send_register_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    if find_user_by_email(email_norm):
        raise HTTPException(409, "该邮箱已注册")

    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "register")

    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@router.post("/auth/login-with-code", summary="邮箱验证码登录")
def api_login_with_code(body: LoginWithCodeDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    user = find_user_by_email(email_norm)
    if not user:
        raise HTTPException(404, "该邮箱未注册")

    sf = get_session_factory()
    with sf() as session:
        vc = (
            session.query(VerificationCode)
            .filter(
                VerificationCode.email == email_norm,
                VerificationCode.code == (body.code or "").strip(),
                VerificationCode.used == False,
                VerificationCode.expires_at > datetime.now(timezone.utc),
            )
            .order_by(VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise HTTPException(401, "验证码无效或已过期")

        vc.used = True
        session.commit()

    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
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


@router.post("/auth/send-reset-password-code", status_code=202, summary="发送重置密码验证码")
def api_send_reset_password_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")
    user = find_user_by_email(email_norm)
    if not user:
        return {
            "ok": True,
            "message": "如果该邮箱已注册，将收到验证码邮件",
            "queued": True,
        }
    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "reset")

    return {
        "ok": True,
        "message": "如果该邮箱已注册，将收到验证码邮件",
        "queued": True,
    }


@router.post("/auth/reset-password", summary="凭邮箱验证码重置密码")
def api_reset_password(body: ResetPasswordDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")
    _verify_and_consume_verification_code(email_norm, body.code)
    u = find_user_by_email(email_norm)
    if not u:
        raise HTTPException(404, "用户不存在")
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == u.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@router.put("/auth/profile", summary="修改当前用户显示名")
def api_update_profile(body: ProfileUpdateDTO, user: User = Depends(_get_current_user)):
    un = (body.username or "").strip()
    sf = get_session_factory()
    with sf() as session:
        taken = session.query(User).filter(User.username == un, User.id != user.id).first()
        if taken:
            raise HTTPException(409, "用户名已被占用")
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.username = un
        session.commit()
    return {"ok": True, "username": un}


@router.post("/auth/change-password", summary="已登录用户修改密码")
def api_change_password(body: PasswordChangeDTO, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        if not verify_password(body.current_password, row.password_hash):
            raise HTTPException(400, "当前密码不正确")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@router.post(
    "/admin/reset-user-password",
    summary="管理员重置用户密码（MODSTORE_ADMIN_RECHARGE_TOKEN）",
    tags=["auth", "admin"],
)
def api_admin_reset_user_password(
    body: AdminResetUserPasswordDTO,
    request: Request,
):
    admin_token = (os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法执行管理员密码重置")
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if client_token != admin_token:
        raise HTTPException(403, "无效的管理员授权")

    un = (body.username or "").strip()
    if not un:
        raise HTTPException(400, "请填写用户名")

    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.username == un).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@router.post("/auth/refresh", summary="用 refresh_token 换取新的 access_token")
def api_refresh_token(body: RefreshTokenDTO):
    refresh_token = body.refresh_token
    if not refresh_token:
        raise HTTPException(400, "缺少刷新令牌")

    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(401, "刷新令牌无效或已过期")

    user_id = int(payload["sub"])
    username = payload["username"]

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    new_access_token = create_access_token(user_id, username, is_admin=bool(user.is_admin))
    new_refresh_token = create_refresh_token(user_id, username)

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


class SendPhoneCodeDTO(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)


class LoginWithPhoneCodeDTO(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    code: str = Field(..., min_length=4, max_length=16)


@router.post("/auth/send-phone-code", summary="发送手机短信验证码")
def api_send_phone_code(body: SendPhoneCodeDTO, request: Request):
    """发送短信验证码登录。当前实现：以邮箱接口替代（若已配置 SMS_PROVIDER 则由运营对接）。
    前端 sendPhoneCode 消费此接口。未配置 SMS 服务时返回 503。
    """
    sms_provider = (os.environ.get("SMS_PROVIDER") or "").strip()
    if not sms_provider:
        raise HTTPException(503, "短信服务未配置，请使用邮箱验证码登录")
    raise HTTPException(501, "短信验证码功能待接入，请联系管理员")


@router.post("/auth/login-with-phone-code", summary="手机验证码登录")
def api_login_with_phone_code(body: LoginWithPhoneCodeDTO):
    """手机验证码登录（与 send-phone-code 配套）。未配置 SMS 时返回 503。"""
    sms_provider = (os.environ.get("SMS_PROVIDER") or "").strip()
    if not sms_provider:
        raise HTTPException(503, "短信服务未配置，请使用邮箱验证码登录")
    raise HTTPException(501, "短信验证码功能待接入，请联系管理员")


class VerifyAdminDigestCodeDTO(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


def normalize_admin_digest_code(raw: str) -> str:
    """与 :mod:`digest_identity` 一致，保留别名供其它模块引用。"""
    return normalize_digest_identity_code(raw)


@router.post(
    "/auth/verify-admin-digest-code",
    summary="校验每日摘要邮件中的 6 位身份码以解锁管理端 UI",
    tags=["auth", "admin"],
)
def api_verify_admin_digest_code(
    body: VerifyAdminDigestCodeDTO,
    user: User = Depends(_require_admin),
):
    """已是管理员 JWT 的账号，凭当日摘要邮件「身份校验码」解锁前端管理端 Tab。

    仅做只读校验：匹配 sha256 + 未过期；**不会** 设置 ``used_at``，避免影响邮件回信侧
    的 ``digest_identity`` 一次性消费逻辑。

    校验实现见 :func:`modstore_server.digest_identity.verify_digest_identity`（与
    ``GET /api/xcmax/admin/digest-identity`` 同源）。
    """
    code = normalize_digest_identity_code(body.code or "")
    if len(code) != 6 or any(c not in "0123456789ABCDEF" for c in code):
        raise HTTPException(400, "身份码格式错误，应为 6 位十六进制")

    sf = get_session_factory()
    with sf() as session:
        expires_iso = verify_digest_identity(session, code)
        if expires_iso:
            return {"ok": True, "expires_at": expires_iso}

    upstream_expires = call_upstream_digest_verify(code)
    if upstream_expires:
        return {"ok": True, "expires_at": upstream_expires}

    raise HTTPException(
        400,
        (
            "身份码无效或已过期。"
            "若需公网市场校验自建库签发的码，请在公网实例配置 MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL，"
            "自建端开启 MODSTORE_DIGEST_PEER_ENABLE_INBOUND=1，且两端使用相同 MODSTORE_DIGEST_PEER_SERVICE_TOKEN（详见 .env.example）。"
        ),
    )


class AccountDeleteDTO(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


@router.post("/auth/account/delete", summary="注销当前账号（软删除）")
def api_account_delete(body: AccountDeleteDTO, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        if getattr(row, "deleted_at", None) is not None:
            return {"ok": True, "message": "账号已注销"}
        if not verify_password(body.password, row.password_hash):
            raise HTTPException(400, "密码不正确")
        row.deleted_at = datetime.now(timezone.utc)
        row.password_hash = hash_password(os.urandom(32).hex())
        session.commit()
    return {"ok": True, "message": "账号已注销"}


@router.get("/auth/export", summary="导出当前账号数据（JSON）")
def api_account_export(user: User = Depends(_get_current_user)):
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
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/admin/status", summary="管理端概要统计（需管理员 JWT）", tags=["auth", "admin"])
def api_admin_status(user: User = Depends(_require_admin)):
    sf = get_session_factory()
    with sf() as session:
        total_items = session.query(CatalogItem).count()
        total_users = session.query(User).count()
        return {
            "ok": True,
            "is_admin": True,
            "total_catalog_items": total_items,
            "total_users": total_users,
        }
