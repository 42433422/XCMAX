# mypy: disable-error-code="arg-type"
"""Public contact form DTO and payload helpers."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from modstore_server.models import LandingContactSubmission

CONTACT_PRIVACY_URL = "/privacy.html"
CONTACT_PRIVACY_VERSION = "2026-06-20"


class PublicContactDTO(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    email: str = Field(..., min_length=4, max_length=256)
    phone: str = Field("", max_length=64)
    company: str = Field("", max_length=256)
    message: str = Field("", max_length=8000)
    source: str = Field("home", max_length=64)
    campaign: str = Field("", max_length=128)
    medium: str = Field("", max_length=64)
    content: str = Field("", max_length=128)
    privacy_agreed: bool = Field(
        default=False,
        description="用户是否已同意用户协议与隐私政策；公开联系表单必须为 true",
    )
    privacy_version: str = Field(default=CONTACT_PRIVACY_VERSION, max_length=32)
    privacy_url: str = Field(default=CONTACT_PRIVACY_URL, max_length=256)
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


_AUDIT_CODE_RE = re.compile(r"^XC-?0*(\d{1,8})$", re.IGNORECASE)


def format_contact_audit_code(submission_id: int) -> str:
    sid = max(0, int(submission_id))
    return f"XC-{sid:06d}"


def parse_contact_audit_code(code: str) -> int | None:
    raw = re.sub(r"\s+", "", (code or "").strip().upper())
    if not raw:
        return None
    match = _AUDIT_CODE_RE.match(raw)
    if match:
        sid = int(match.group(1))
        return sid if sid > 0 else None
    if raw.isdigit():
        sid = int(raw)
        return sid if sid > 0 else None
    return None


def normalize_desktop_os(value: str | None) -> str:
    raw = (value or "").strip().casefold()
    if raw in ("mac", "macos", "darwin", "osx"):
        return "mac"
    if raw in ("win", "windows", "win32", "pc"):
        return "win"
    return ""


def normalize_contact_tracking_fields(
    campaign: object = "",
    medium: object = "",
    content: object = "",
) -> dict[str, str]:
    return {
        "campaign": str(campaign or "").strip()[:128],
        "medium": str(medium or "").strip()[:64],
        "content": str(content or "").strip()[:128],
    }


def landing_submission_payload(row: LandingContactSubmission) -> dict:
    try:
        meta = json.loads(row.meta_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    created = row.created_at
    submitted_at = created.isoformat() if created else ""
    desktop_os = normalize_desktop_os(str(meta.get("desktop_os") or ""))
    need_mobile = meta.get("need_mobile")
    need_mobile_val = (
        True
        if need_mobile is None
        else (
            bool(need_mobile)
            if isinstance(need_mobile, bool)
            else str(need_mobile).lower() not in ("0", "false", "no")
        )
    )
    return {
        "landing_contact_id": row.id,
        "audit_code": format_contact_audit_code(row.id),
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "company": row.company,
        "message": row.message,
        "source": row.source,
        "intake_source": row.source,
        **normalize_contact_tracking_fields(
            meta.get("campaign"),
            meta.get("medium"),
            meta.get("content"),
        ),
        "desktop_os": desktop_os or None,
        "need_mobile": need_mobile_val,
        "privacy_agreed": bool(meta.get("privacy_agreed")),
        "privacy_version": str(meta.get("privacy_version") or CONTACT_PRIVACY_VERSION).strip()[:32],
        "privacy_url": str(meta.get("privacy_url") or CONTACT_PRIVACY_URL).strip()[:256],
        "privacy_agreed_at": str(meta.get("privacy_agreed_at") or "").strip(),
        "market_user_id": int(meta.get("market_user_id") or 0) or None,
        "submitted_at": submitted_at,
        "created_at": submitted_at,
    }
