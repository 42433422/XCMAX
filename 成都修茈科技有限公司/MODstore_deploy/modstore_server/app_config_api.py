"""移动端 / 商店合规：应用配置、反馈。"""

from __future__ import annotations

import os
import json
from pathlib import Path
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


def _empty_delta() -> Dict[str, Any]:
    return {
        "available": False,
        "format": "",
        "patch_url": "",
        "base_version_code": 0,
        "base_version_name": "",
        "target_version_code": 0,
        "target_version_name": "",
        "patch_sha256": "",
        "base_apk_sha256": "",
        "target_apk_sha256": "",
        "patch_size": 0,
        "apk_size": 0,
    }


def _delta_manifest_path(sku: str) -> Path:
    explicit = os.environ.get("XCAGI_ANDROID_DELTA_MANIFEST", "").strip()
    if explicit:
        return Path(explicit)
    return Path(f"/var/www/update/releases/stable/{sku}/android_delta_manifest.json")


def _apk_delta(sku: str, current_version_code: int) -> Dict[str, Any]:
    if current_version_code <= 0:
        return _empty_delta()
    path = _delta_manifest_path(sku)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_delta()
    if manifest.get("target_version_code") != _ANDROID_LATEST_VERSION:
        return _empty_delta()
    if (manifest.get("target_version_name") or "") != _ANDROID_LATEST_NAME:
        return _empty_delta()
    patches = manifest.get("patches")
    if not isinstance(patches, list):
        return _empty_delta()
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        if int(patch.get("base_version_code") or 0) != current_version_code:
            continue
        out = _empty_delta()
        out.update(
            {
                "available": True,
                "format": str(patch.get("format") or "xcagi-copy-data-v1"),
                "patch_url": str(patch.get("patch_url") or ""),
                "base_version_code": int(patch.get("base_version_code") or 0),
                "base_version_name": str(patch.get("base_version_name") or ""),
                "target_version_code": int(patch.get("target_version_code") or 0),
                "target_version_name": str(patch.get("target_version_name") or ""),
                "patch_sha256": str(patch.get("patch_sha256") or ""),
                "base_apk_sha256": str(patch.get("base_apk_sha256") or ""),
                "target_apk_sha256": str(patch.get("target_apk_sha256") or ""),
                "patch_size": int(patch.get("patch_size") or 0),
                "apk_size": int(patch.get("apk_size") or 0),
            }
        )
        if out["patch_url"]:
            return out
    return _empty_delta()


_PROFILE_PAGE_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "revision": os.environ.get("XCAGI_PROFILE_PAGE_REVISION", "2026-06-26.profile-hot-v1").strip()
    or "2026-06-26.profile-hot-v1",
    "hero_variant": os.environ.get("XCAGI_PROFILE_PAGE_HERO_VARIANT", "glass").strip() or "glass",
    "headline": os.environ.get("XCAGI_PROFILE_PAGE_HEADLINE", "XCAGI 企业工作身份").strip()
    or "XCAGI 企业工作身份",
    "subtitle": os.environ.get("XCAGI_PROFILE_PAGE_SUBTITLE", "账号、工作台与执行端状态统一管理").strip()
    or "账号、工作台与执行端状态统一管理",
    "status_ready": os.environ.get("XCAGI_PROFILE_PAGE_STATUS_READY", "资料、头像和工作台状态已同步").strip()
    or "资料、头像和工作台状态已同步",
    "status_syncing": os.environ.get("XCAGI_PROFILE_PAGE_STATUS_SYNCING", "正在同步资料与工作台状态").strip()
    or "正在同步资料与工作台状态",
    "primary_chip": os.environ.get("XCAGI_PROFILE_PAGE_PRIMARY_CHIP", "").strip(),
    "secondary_chip": os.environ.get("XCAGI_PROFILE_PAGE_SECONDARY_CHIP", "").strip(),
    "accent": os.environ.get("XCAGI_PROFILE_PAGE_ACCENT", "violet").strip() or "violet",
}

_PROFILE_PAGE_KEYS = set(_PROFILE_PAGE_DEFAULTS.keys())


def _profile_page_path(sku: str) -> Path:
    explicit = os.environ.get("XCAGI_PROFILE_PAGE_CONFIG", "").strip()
    if explicit:
        return Path(explicit)
    return Path(f"/var/www/update/releases/stable/{sku}/profile_page.json")


def _profile_page_config(sku: str) -> Dict[str, Any]:
    config = dict(_PROFILE_PAGE_DEFAULTS)
    path = _profile_page_path(sku)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = None
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key not in _PROFILE_PAGE_KEYS:
                continue
            if key == "enabled":
                if isinstance(value, bool):
                    config[key] = value
                elif isinstance(value, str):
                    config[key] = value.strip().lower() in ("1", "true", "yes", "on")
                continue
            config[key] = str(value or "").strip()
    return config


@router.get("/app/config", summary="Android/iOS 客户端配置（合规、版本）")
def api_app_config(
    platform: str = Query("android", max_length=32),
    sku: str = Query("personal", pattern="^(personal|enterprise)$"),
    current_version_code: int = Query(0, ge=0),
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
        "apk_delta": _apk_delta(sku_norm, current_version_code),
        "profile_page": _profile_page_config(sku_norm),
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
