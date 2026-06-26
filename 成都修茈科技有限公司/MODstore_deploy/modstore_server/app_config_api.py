"""移动端 / 商店合规：应用配置、反馈。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.market_shared import _get_current_user
from modstore_server.models import LandingContactSubmission, User, get_session_factory

router = APIRouter(tags=["app"])

_DEFAULT_BASE = "https://xiu-ci.com"
_LEGAL_VERSION = os.environ.get("XCAGI_LEGAL_VERSION", "1").strip() or "1"
_ICP_NUMBER = (
    os.environ.get("XCAGI_ICP_NUMBER", "蜀ICP备2026014056号-3A").strip() or "蜀ICP备2026014056号-3A"
)
_APP_FILING_NUMBER = (
    os.environ.get("XCAGI_APP_FILING_NUMBER", "蜀ICP备2026014056号-3A").strip()
    or os.environ.get("XCAGI_ANDROID_APP_FILING_NUMBER", "").strip()
    or "蜀ICP备2026014056号-3A"
)
_APP_FILING_APPROVED = (
    os.environ.get("XCAGI_ANDROID_APP_FILING_APPROVED", "1") or ""
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# versionCode / versionName 对齐 FHD/VERSION.md v10 锚点与 mobile-android/app/build.gradle.kts
_ANDROID_MIN_VERSION = int(os.environ.get("XCAGI_ANDROID_MIN_VERSION_CODE", "10") or "10")
_ANDROID_LATEST_VERSION = int(os.environ.get("XCAGI_ANDROID_LATEST_VERSION_CODE", "10") or "10")
_ANDROID_LATEST_NAME = (
    os.environ.get("XCAGI_ANDROID_LATEST_VERSION_NAME", "10.0.0").strip() or "10.0.0"
)
_ANDROID_FORCE_UPDATE = os.environ.get("XCAGI_ANDROID_FORCE_UPDATE", "").strip() in (
    "1",
    "true",
    "yes",
)


def _apk_url(sku: str) -> str:
    base = (os.environ.get("XCAGI_ANDROID_DOWNLOAD_BASE") or _DEFAULT_BASE).rstrip("/")
    if sku == "enterprise":
        return f"{base}/download/enterprise/XCAGI-Enterprise-Android-{_ANDROID_LATEST_NAME}.apk"
    return f"{base}/download/personal/XCAGI-Personal-Android-{_ANDROID_LATEST_NAME}.apk"


@router.get("/app/config", summary="Android/iOS 客户端配置（合规、版本）")
def api_app_config(
    platform: str = Query("android", max_length=32),
    sku: str = Query("personal", pattern="^(personal|enterprise)$"),
) -> Dict[str, Any]:
    base = (os.environ.get("XCAGI_PUBLIC_BASE_URL") or _DEFAULT_BASE).rstrip("/")
    sku_norm = sku if sku in ("personal", "enterprise") else "personal"
    return {
        "ok": True,
        "platform": platform,
        "sku": sku_norm,
        "privacy_url": f"{base}/legal/privacy",
        "terms_url": f"{base}/legal/terms",
        "legal_version": _LEGAL_VERSION,
        "icp_number": _ICP_NUMBER,
        "app_filing_approved": _APP_FILING_APPROVED,
        "app_filing_beian_url": "https://beian.miit.gov.cn/",
        "app_filing_number": _APP_FILING_NUMBER,
        "min_android_version": _ANDROID_MIN_VERSION,
        "latest_android_version": _ANDROID_LATEST_VERSION,
        "latest_android_version_name": _ANDROID_LATEST_NAME,
        "force_update": _ANDROID_FORCE_UPDATE,
        "apk_download_url": _apk_url(sku_norm),
        "feedback_email": os.environ.get("XCAGI_FEEDBACK_EMAIL", "support@xiu-ci.com").strip(),
    }


class AppFeedbackDTO(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    contact: str = Field("", max_length=256)
    app_version: str = Field("", max_length=32)
    sku: str = Field("personal", max_length=32)
    platform: str = Field("android", max_length=32)


@router.post("/app/feedback", summary="应用内反馈（需登录）")
def api_app_feedback(
    body: AppFeedbackDTO,
    user: User = Depends(_get_current_user),
):
    meta = {
        "user_id": user.id,
        "username": user.username,
        "app_version": (body.app_version or "")[:32],
        "sku": (body.sku or "personal")[:32],
        "platform": (body.platform or "android")[:32],
        "contact": (body.contact or "")[:256],
    }
    import json

    row = LandingContactSubmission(
        name=(user.username or "app-user")[:128],
        email=(user.email or body.contact or "app-feedback@local")[:256],
        phone="",
        company=f"xcagi-mobile:{body.sku}",
        message=(body.message or "").strip()[:8000],
        source="app_feedback",
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    sf = get_session_factory()
    with sf() as session:
        session.add(row)
        session.commit()
        new_id = row.id
    return {"ok": True, "id": new_id}
