"""官网需求采集表单：专属链接签名、提交同步 pipeline。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode, urlparse, urlunparse

import httpx

from app.services.user_cs_pipeline import (
    auto_advance_pipeline_if_ready,
    load_pipeline,
    save_pipeline,
    set_pipeline_stage,
)

logger = logging.getLogger(__name__)

DEFAULT_FORM_BASE = (
    os.environ.get("XCAGI_DEMAND_FORM_URL", "https://xiu-ci.com/contact.html").strip()
    or "https://xiu-ci.com/contact.html"
)
_LINK_SECRET = (
    os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET", "xcagi-cs-intake-dev-secret").strip()
    or "xcagi-cs-intake-dev-secret"
)
_WEBHOOK_SECRET = (os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_SECRET", "") or _LINK_SECRET).strip()
_MARKET_BASE = (
    (os.environ.get("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com") or "").strip().rstrip("/")
)
_MARKET_INTERNAL_KEY = (os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY", "") or _LINK_SECRET).strip()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def sign_cs_intake_token(market_user_id: int, *, ttl_sec: int = 60 * 60 * 24 * 30) -> str:
    """与 MODstore ``cs_intake_link.verify_cs_intake_token`` 算法一致。"""
    uid = int(market_user_id)
    exp = int(time.time()) + int(ttl_sec)
    payload = f"{uid}:{exp}"
    sig = hmac.new(_LINK_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(f"{payload}:{_b64url(sig)}".encode("utf-8"))


def verify_cs_intake_token(market_user_id: int, token: str) -> bool:
    try:
        raw = _b64url_decode((token or "").strip()).decode("utf-8")
        payload, sig = raw.rsplit(":", 1)
        uid_s, exp_s = payload.split(":", 1)
        if int(uid_s) != int(market_user_id):
            return False
        if int(exp_s) < int(time.time()):
            return False
        expect = hmac.new(
            _LINK_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).digest()
        return hmac.compare_digest(_b64url(expect), sig)
    except (ValueError, OSError, UnicodeDecodeError):
        return False


def resolve_intake_prefill(
    market_user_id: int,
    *,
    username: str = "",
    client_name: str = "",
) -> dict[str, str]:
    """
    表单预填：优先 ERP/CRM 匹配的公司名，避免把市场登录名（如 SUNBIRD）写入姓名字段。
    返回 company、contact_name、form_name（姓名预填）、greeting_name（话术称呼）。
    """
    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    login = (username or str(doc.get("username") or "")).strip()
    hint = (client_name or "").strip()
    if login and hint.casefold() == login.casefold():
        hint = ""

    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = (
        str(form.get("company") or "").strip() or str(doc.get("erp_customer_name") or "").strip()
    )
    contact = hint or str(form.get("name") or "").strip()
    if login and contact.casefold() == login.casefold():
        contact = ""

    if not company or not contact:
        try:
            from app.services.user_cs_crm_store import get_opportunity_by_market_user

            opp = get_opportunity_by_market_user(uid)
            if opp:
                if not company:
                    company = (
                        str(opp.get("company") or "").strip() or str(opp.get("title") or "").strip()
                    )
                if not contact:
                    contact = str(opp.get("contact_name") or "").strip()
                    if login and contact.casefold() == login.casefold():
                        contact = ""
        except Exception:
            logger.debug("resolve_intake_prefill crm lookup skipped", exc_info=True)

    form_name = company or contact
    greeting = company or contact or login
    return {
        "company": company,
        "contact_name": contact,
        "form_name": form_name,
        "greeting_name": greeting,
        "login_name": login,
    }


def build_intake_form_url(
    market_user_id: int,
    *,
    brief: str = "",
    client_name: str = "",
    company: str = "",
    contact_name: str = "",
    base_url: str = "",
) -> str:
    base = (base_url or DEFAULT_FORM_BASE).strip() or DEFAULT_FORM_BASE
    parsed = urlparse(base)
    q: dict[str, str] = {
        "cs_uid": str(int(market_user_id)),
        "cs_t": sign_cs_intake_token(int(market_user_id)),
    }
    brief = (brief or "").strip()
    if brief:
        q["brief"] = _b64url(brief.encode("utf-8")[:600])

    pre = resolve_intake_prefill(int(market_user_id), client_name=client_name)
    co = (company or pre["company"]).strip()
    ct = (contact_name or pre["contact_name"]).strip()
    cn = (client_name or "").strip()
    if not cn or (pre["login_name"] and cn.casefold() == pre["login_name"].casefold()):
        cn = (pre["form_name"] or pre["greeting_name"]).strip()
    elif not co and cn:
        co = cn

    if co:
        q["cs_company"] = quote(co[:256])
    form_name = co or ct or cn
    if form_name:
        q["cs_name"] = quote(form_name[:128])
    if ct and ct.casefold() != form_name.casefold():
        q["cs_contact"] = quote(ct[:128])

    new_query = urlencode(q)
    fragment = parsed.fragment or "contact"
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, fragment)
    )


def apply_landing_submission_to_pipeline(
    market_user_id: int,
    submission: dict[str, Any],
    *,
    username: str = "",
    notify_wechat: bool = True,
) -> dict[str, Any]:
    uid = int(market_user_id)
    from app.services.user_cs_intake_finalize import (
        bootstrap_pipeline_lead,
        finalize_intake_submission,
    )

    doc = bootstrap_pipeline_lead(uid, username=username)
    now = datetime.now(timezone.utc).isoformat()
    from app.services.user_cs_software_delivery import (
        normalize_desktop_os,
        parse_desktop_os_from_message,
    )

    desktop_os = normalize_desktop_os(str(submission.get("desktop_os") or ""))
    message = str(submission.get("message") or "")[:8000]
    if not desktop_os:
        desktop_os = parse_desktop_os_from_message(message)
    form = {
        "name": str(submission.get("name") or "")[:128],
        "email": str(submission.get("email") or "")[:256],
        "phone": str(submission.get("phone") or "")[:64],
        "company": str(submission.get("company") or "")[:256],
        "message": message,
    }
    if desktop_os:
        form["desktop_os"] = desktop_os
    from app.services.user_cs_software_delivery import normalize_need_mobile

    if "need_mobile" in submission:
        form["need_mobile"] = normalize_need_mobile(submission.get("need_mobile"), default=True)
    doc["intake_form"] = form
    doc["intake_submitted_at"] = str(submission.get("submitted_at") or now)
    src = str(submission.get("intake_source") or "").strip()
    if src:
        doc["intake_source"] = src[:64]
    lid = submission.get("landing_contact_id")
    if lid is not None:
        doc["landing_contact_id"] = int(lid)
    doc.setdefault("intake_sent", True)
    doc = save_pipeline(doc)
    stage = str(doc.get("stage") or "idle")
    try:
        from app.services.user_cs_pipeline import _stage_rank

        if _stage_rank(stage) >= _stage_rank("connected"):
            from app.services.user_cs_market_profile import (
                apply_enterprise_profile_to_pipeline_doc,
                ensure_enterprise_profile_from_intake,
            )

            profile = ensure_enterprise_profile_from_intake(
                uid,
                company=form.get("company") or "",
                contact_name=form.get("name") or username or "",
            )
            doc = apply_enterprise_profile_to_pipeline_doc(doc, profile)
            doc = save_pipeline(doc)

        if _stage_rank(stage) < _stage_rank("intake_done"):
            doc = set_pipeline_stage(
                uid,
                "intake_done",
                username=username,
                source="cs_intake_form",
                note="landing_contact_submitted",
            )
    except ValueError:
        pass
    doc, _ = auto_advance_pipeline_if_ready(uid, username=username)
    doc, _finalize_meta = finalize_intake_submission(
        uid,
        doc,
        username=username,
        notify_wechat=notify_wechat,
    )
    return doc


def verify_webhook_secret(header_value: str | None) -> bool:
    if not _WEBHOOK_SECRET:
        return True
    return bool(header_value) and hmac.compare_digest(str(header_value).strip(), _WEBHOOK_SECRET)


async def poll_market_intake_submission(market_user_id: int) -> dict[str, Any] | None:
    """从 MODstore 内部 API 拉取该客户最新 cs_intake 提交。"""
    if not _MARKET_BASE or not _MARKET_INTERNAL_KEY:
        return None
    url = f"{_MARKET_BASE}/api/internal/cs-intake/latest"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(
                url,
                params={"market_user_id": int(market_user_id)},
                headers={"X-Internal-Api-Key": _MARKET_INTERNAL_KEY},
            )
        if res.status_code != 200:
            return None
        data = res.json()
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        row = data.get("submission")
        return row if isinstance(row, dict) else None
    except Exception:
        logger.debug("poll_market_intake_submission failed", exc_info=True)
        return None


async def _request_submission_by_audit_code(
    audit_code: str,
    *,
    market_user_id: int | None = None,
    bind: bool = True,
) -> dict[str, Any]:
    if not _MARKET_BASE or not _MARKET_INTERNAL_KEY:
        raise ValueError("市场服务未配置，无法校验审核码（请检查 XCAGI_MARKET_BASE_URL）")
    code = (audit_code or "").strip()
    if not code:
        raise ValueError("请填写审核码")
    params: dict[str, str | int | bool] = {"code": code, "bind": bool(bind)}
    if market_user_id:
        params["market_user_id"] = int(market_user_id)
    url = f"{_MARKET_BASE}/api/internal/contact/by-audit-code"
    async with httpx.AsyncClient(timeout=12.0) as client:
        res = await client.get(
            url,
            params=params,
            headers={"X-Internal-Api-Key": _MARKET_INTERNAL_KEY},
        )
    if res.status_code == 404:
        raise ValueError("未找到该审核码对应的需求单，请让客户核对或重新提交")
    if res.status_code == 409:
        try:
            detail = res.json().get("detail")
        except Exception:
            detail = res.text
        raise ValueError(str(detail or "该审核码已绑定其他客户"))
    if res.status_code == 400:
        try:
            detail = res.json().get("detail")
        except Exception:
            detail = res.text
        raise ValueError(str(detail or "审核码格式不正确"))
    if res.status_code != 200:
        raise ValueError(f"获取需求单失败（HTTP {res.status_code}）")
    data = res.json()
    if not isinstance(data, dict) or not data.get("ok"):
        raise ValueError("获取需求单失败")
    row = data.get("submission")
    if not isinstance(row, dict):
        raise ValueError("未返回需求单内容")
    return dict(row)


async def fetch_submission_by_audit_code(
    audit_code: str,
    *,
    market_user_id: int | None = None,
) -> dict[str, Any]:
    """按审核码只读拉取官网问卷内容，不绑定客户、不推进阶段。"""
    return await _request_submission_by_audit_code(
        audit_code,
        market_user_id=market_user_id,
        bind=False,
    )


async def redeem_submission_by_audit_code(
    market_user_id: int,
    audit_code: str,
    *,
    username: str = "",
) -> dict[str, Any]:
    """客服在进度面板输入客户官网审核码，拉取需求单并写入 pipeline、推进阶段。"""
    row = await _request_submission_by_audit_code(
        audit_code,
        market_user_id=int(market_user_id),
        bind=True,
    )
    row["intake_source"] = "audit_code"
    return apply_landing_submission_to_pipeline(int(market_user_id), row, username=username)


def notify_market_landing_crm_link(
    landing_contact_id: int | None,
    crm_opportunity_id: int | None,
    *,
    market_user_id: int | None = None,
) -> None:
    """回写 MODstore landing_contact_submissions.meta_json 的 CRM 商机 ID。"""
    lid = int(landing_contact_id or 0)
    oid = int(crm_opportunity_id or 0)
    if lid <= 0 or oid <= 0 or not _MARKET_BASE or not _MARKET_INTERNAL_KEY:
        return
    url = f"{_MARKET_BASE}/api/internal/contact/link-crm"
    payload: dict[str, Any] = {
        "landing_contact_id": lid,
        "crm_opportunity_id": oid,
    }
    if market_user_id:
        payload["market_user_id"] = int(market_user_id)
    try:
        httpx.post(
            url,
            json=payload,
            headers={"X-Internal-Api-Key": _MARKET_INTERNAL_KEY},
            timeout=8.0,
        )
    except Exception:
        logger.debug("notify_market_landing_crm_link failed", exc_info=True)


async def sync_intake_from_market_if_newer(
    market_user_id: int, *, username: str = ""
) -> dict[str, Any] | None:
    row = await poll_market_intake_submission(market_user_id)
    if not row:
        return None
    doc = load_pipeline(int(market_user_id), username=username)
    existing_at = str(doc.get("intake_submitted_at") or "")
    new_at = str(row.get("created_at") or row.get("submitted_at") or "")
    if existing_at and new_at and existing_at >= new_at:
        return doc
    return apply_landing_submission_to_pipeline(int(market_user_id), row, username=username)
