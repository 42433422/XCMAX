"""移动端 / 商店合规：应用配置、反馈。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from modstore_server.market_shared import _get_current_user
from modstore_server.models import LandingContactSubmission, User, get_session_factory

router = APIRouter(tags=["app"])
_LOG = logging.getLogger(__name__)

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

_VALID_SKUS = frozenset({"personal", "enterprise"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
_MAX_ANDROID_VERSION_CODE = 2_100_000_000


@dataclass(frozen=True)
class _AndroidRelease:
    sku: str
    version_code: int
    version_name: str
    min_version_code: int
    force_update: bool
    download_url: str
    apk_sha256: str
    apk_size: int
    artifact_path: Path
    source: str


def _release_root() -> Path:
    raw = os.environ.get("XCAGI_ANDROID_RELEASE_ROOT", "").strip()
    return Path(raw) if raw else Path("/var/www/update/releases/stable")


def _public_base_url() -> str:
    raw = (os.environ.get("XCAGI_PUBLIC_BASE_URL") or _DEFAULT_BASE).strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return _DEFAULT_BASE
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return _DEFAULT_BASE
    return raw


def _release_manifest_path(sku: str) -> tuple[Path, bool]:
    specific = os.environ.get(f"XCAGI_ANDROID_RELEASE_MANIFEST_{sku.upper()}", "").strip()
    if specific:
        return Path(specific), True
    generic = os.environ.get("XCAGI_ANDROID_RELEASE_MANIFEST", "").strip()
    if generic:
        rendered = generic.replace("{sku}", sku)
        path = Path(rendered)
        if path.suffix.lower() != ".json":
            path = path / sku / "android_release_manifest.json"
        return path, True
    return _release_root() / sku / "android_release_manifest.json", False


def _safe_int(value: Any, *, minimum: int = 0, maximum: int = _MAX_ANDROID_VERSION_CODE) -> int:
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        parsed = int(value)
    else:
        return -1
    return parsed if minimum <= parsed <= maximum else -1


def _safe_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    return None


def _expected_apk_name(sku: str, version_name: str) -> str:
    edition = "Enterprise" if sku == "enterprise" else "Personal"
    return f"XCAGI-{edition}-Android-{version_name}.apk"


def _allowed_download_hosts() -> set[str]:
    hosts = {"xiu-ci.com"}
    for raw in (
        os.environ.get("XCAGI_PUBLIC_BASE_URL", ""),
        os.environ.get("XCAGI_ANDROID_DOWNLOAD_BASE", ""),
    ):
        try:
            parsed = urlsplit(raw.strip()) if raw.strip() else None
        except ValueError:
            continue
        if parsed and parsed.hostname:
            hosts.add(parsed.hostname.lower())
    hosts.update(
        host.strip().lower()
        for host in os.environ.get("XCAGI_ANDROID_DOWNLOAD_HOSTS", "").split(",")
        if host.strip()
    )
    return hosts


def _download_url_is_valid(url: str, *, sku: str, filename: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.hostname.lower() not in _allowed_download_hosts()
        or parsed.query
        or parsed.fragment
    ):
        return False
    path = unquote(parsed.path)
    parts = [part for part in path.split("/") if part]
    if not any(
        part == "download" and index + 1 < len(parts) and parts[index + 1] == sku
        for index, part in enumerate(parts)
    ):
        return False
    return bool(parts and parts[-1] == filename)


@lru_cache(maxsize=32)
def _artifact_sha256(path: str, mtime_ns: int, ctime_ns: int, size: int) -> str:
    del mtime_ns, ctime_ns, size
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_matches(path: Path, *, expected_sha256: str, expected_size: int) -> bool:
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size != expected_size:
            return False
        actual = _artifact_sha256(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except OSError:
        return False
    return actual == expected_sha256


def _validate_release(
    raw: Any,
    *,
    sku: str,
    manifest_path: Path,
    current_version_code: int,
    source: str,
) -> Optional[_AndroidRelease]:
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != 1 or raw.get("platform") != "android":
        return None
    if str(raw.get("sku") or "").strip().lower() != sku:
        return None
    if raw.get("channel", "stable") != "stable":
        return None
    version_code = _safe_int(raw.get("version_code"), minimum=1)
    version_name = str(raw.get("version_name") or "").strip()
    min_version_code = _safe_int(raw.get("min_version_code", 0), minimum=0)
    force_update = _safe_bool(raw.get("force_update", False))
    apk_sha256 = str(raw.get("sha256") or "").strip().lower()
    apk_size = _safe_int(raw.get("size"), minimum=1, maximum=2**63 - 1)
    download_url = str(raw.get("download_url") or "").strip()
    if (
        version_code < 1
        or not _VERSION_NAME_RE.fullmatch(version_name)
        or min_version_code < 0
        or min_version_code > version_code
        or force_update is None
        or not _SHA256_RE.fullmatch(apk_sha256)
        or apk_size < 1
    ):
        return None
    expected_name = _expected_apk_name(sku, version_name)
    artifact_name = str(raw.get("artifact") or expected_name).strip()
    if artifact_name != expected_name or Path(artifact_name).name != artifact_name:
        return None
    if not _download_url_is_valid(download_url, sku=sku, filename=expected_name):
        return None
    parent = manifest_path.parent.resolve()
    artifact_path = (manifest_path.parent / artifact_name).resolve()
    if artifact_path.parent != parent:
        return None
    if not _artifact_matches(
        artifact_path,
        expected_sha256=apk_sha256,
        expected_size=apk_size,
    ):
        return None
    # A valid manifest must never advertise a downgrade or reinstall as an update.
    if current_version_code > 0 and version_code <= current_version_code:
        return None
    return _AndroidRelease(
        sku=sku,
        version_code=version_code,
        version_name=version_name,
        min_version_code=min_version_code,
        force_update=force_update,
        download_url=download_url,
        apk_sha256=apk_sha256,
        apk_size=apk_size,
        artifact_path=artifact_path,
        source=source,
    )


def _legacy_env_value(name: str, sku: str) -> str:
    specific = os.environ.get(f"{name}_{sku.upper()}", "").strip()
    if specific:
        return specific
    legacy_sku = os.environ.get("XCAGI_ANDROID_LEGACY_SKU", "enterprise").strip().lower()
    return os.environ.get(name, "").strip() if legacy_sku == sku else ""


def _legacy_env_release(
    sku: str,
    *,
    manifest_path: Path,
    current_version_code: int,
) -> Optional[_AndroidRelease]:
    code = _legacy_env_value("XCAGI_ANDROID_LATEST_VERSION_CODE", sku)
    name = _legacy_env_value("XCAGI_ANDROID_LATEST_VERSION_NAME", sku)
    sha256 = _legacy_env_value("XCAGI_ANDROID_APK_SHA256", sku)
    size = _legacy_env_value("XCAGI_ANDROID_APK_SIZE", sku)
    if not all((code, name, sha256, size)):
        return None
    direct_url = _legacy_env_value("XCAGI_ANDROID_APK_DOWNLOAD_URL", sku)
    if direct_url:
        download_url = direct_url
    else:
        base = (os.environ.get("XCAGI_ANDROID_DOWNLOAD_BASE") or _DEFAULT_BASE).rstrip("/")
        download_url = f"{base}/download/{sku}/{_expected_apk_name(sku, name)}"
    raw = {
        "schema_version": 1,
        "platform": "android",
        "channel": "stable",
        "sku": sku,
        "version_code": code,
        "version_name": name,
        "min_version_code": _legacy_env_value("XCAGI_ANDROID_MIN_VERSION_CODE", sku) or 0,
        "force_update": _legacy_env_value("XCAGI_ANDROID_FORCE_UPDATE", sku).lower()
        in {"1", "true", "yes", "on"},
        "download_url": download_url,
        "sha256": sha256,
        "size": size,
        "artifact": _expected_apk_name(sku, name),
    }
    release = _validate_release(
        raw,
        sku=sku,
        manifest_path=manifest_path,
        current_version_code=0,
        source="legacy_env",
    )
    if release and current_version_code > 0 and release.version_code <= current_version_code:
        return None
    return release


def _android_release(sku: str, current_version_code: int) -> Optional[_AndroidRelease]:
    if sku not in _VALID_SKUS:
        return None
    manifest_path, explicitly_configured = _release_manifest_path(sku)
    if manifest_path.exists():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _LOG.warning("android release manifest unreadable sku=%s", sku)
            return None
        release = _validate_release(
            raw,
            sku=sku,
            manifest_path=manifest_path,
            current_version_code=0,
            source="manifest",
        )
        if release is None:
            _LOG.warning("android release manifest rejected sku=%s", sku)
        elif current_version_code > 0 and release.version_code <= current_version_code:
            return None
        return release
    if explicitly_configured:
        return None
    return _legacy_env_release(
        sku,
        manifest_path=manifest_path,
        current_version_code=current_version_code,
    )


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
    specific = os.environ.get(f"XCAGI_ANDROID_DELTA_MANIFEST_{sku.upper()}", "").strip()
    if specific:
        return Path(specific)
    explicit = os.environ.get("XCAGI_ANDROID_DELTA_MANIFEST", "").strip()
    if explicit:
        rendered = explicit.replace("{sku}", sku)
        path = Path(rendered)
        if path.suffix.lower() != ".json":
            path = path / sku / "android_delta_manifest.json"
        return path
    return _release_root() / sku / "android_delta_manifest.json"


def _apk_delta(
    sku: str,
    current_version_code: int,
    release: Optional[_AndroidRelease],
) -> Dict[str, Any]:
    if current_version_code <= 0 or release is None:
        return _empty_delta()
    path = _delta_manifest_path(sku)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_delta()
    if not isinstance(manifest, dict):
        return _empty_delta()
    if str(manifest.get("sku") or "").strip().lower() != sku:
        return _empty_delta()
    if manifest.get("target_version_code") != release.version_code:
        return _empty_delta()
    if (manifest.get("target_version_name") or "") != release.version_name:
        return _empty_delta()
    patches = manifest.get("patches")
    if not isinstance(patches, list):
        return _empty_delta()
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        base_version_code = _safe_int(patch.get("base_version_code"), minimum=1)
        target_version_code = _safe_int(patch.get("target_version_code"), minimum=1)
        if base_version_code != current_version_code:
            continue
        if target_version_code != release.version_code:
            continue
        if str(patch.get("target_version_name") or "") != release.version_name:
            continue
        if str(patch.get("format") or "") != "xcagi-copy-data-v1":
            continue
        patch_url = str(patch.get("patch_url") or "").strip()
        try:
            patch_name = Path(unquote(urlsplit(patch_url).path)).name
        except ValueError:
            continue
        patch_sha256 = str(patch.get("patch_sha256") or "").strip().lower()
        base_sha256 = str(patch.get("base_apk_sha256") or "").strip().lower()
        target_sha256 = str(patch.get("target_apk_sha256") or "").strip().lower()
        patch_size = _safe_int(patch.get("patch_size"), minimum=1, maximum=2**63 - 1)
        apk_size = _safe_int(patch.get("apk_size"), minimum=1, maximum=2**63 - 1)
        if (
            not patch_name.endswith(".xcapkdiff")
            or not _download_url_is_valid(patch_url, sku=sku, filename=patch_name)
            or not _SHA256_RE.fullmatch(patch_sha256)
            or not _SHA256_RE.fullmatch(base_sha256)
            or target_sha256 != release.apk_sha256
            or patch_size < 1
            or apk_size != release.apk_size
        ):
            continue
        patch_artifact = (path.parent / patch_name).resolve()
        if patch_artifact.parent != path.parent.resolve() or not _artifact_matches(
            patch_artifact,
            expected_sha256=patch_sha256,
            expected_size=patch_size,
        ):
            continue
        out = _empty_delta()
        out.update(
            {
                "available": True,
                "format": "xcagi-copy-data-v1",
                "patch_url": str(patch.get("patch_url") or ""),
                "base_version_code": base_version_code,
                "base_version_name": str(patch.get("base_version_name") or ""),
                "target_version_code": target_version_code,
                "target_version_name": str(patch.get("target_version_name") or ""),
                "patch_sha256": patch_sha256,
                "base_apk_sha256": base_sha256,
                "target_apk_sha256": target_sha256,
                "patch_size": patch_size,
                "apk_size": apk_size,
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
    "subtitle": os.environ.get(
        "XCAGI_PROFILE_PAGE_SUBTITLE", "账号、工作台与执行端状态统一管理"
    ).strip()
    or "账号、工作台与执行端状态统一管理",
    "status_ready": os.environ.get(
        "XCAGI_PROFILE_PAGE_STATUS_READY", "资料、头像和工作台状态已同步"
    ).strip()
    or "资料、头像和工作台状态已同步",
    "status_syncing": os.environ.get(
        "XCAGI_PROFILE_PAGE_STATUS_SYNCING", "正在同步资料与工作台状态"
    ).strip()
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


def _explicit_https_url(*names: str) -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        if (
            parsed.scheme.lower() == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return raw
    return ""


@router.get("/app/config", summary="Android/iOS 客户端配置（合规、版本）")
def api_app_config(
    platform: str = Query("android", max_length=32),
    sku: str = Query("personal", pattern="^(personal|enterprise)$"),
    current_version_code: int = Query(0, ge=0),
) -> Dict[str, Any]:
    base = _public_base_url()
    sku_norm = sku if sku in ("personal", "enterprise") else "personal"
    release = (
        _android_release(sku_norm, current_version_code)
        if platform.strip().lower() == "android"
        else None
    )
    privacy_url = _explicit_https_url("XCAGI_PRIVACY_URL", "XCAGI_LEGAL_PRIVACY_URL")
    terms_url = _explicit_https_url("XCAGI_TERMS_URL", "XCAGI_LEGAL_TERMS_URL")
    default_legal_url = f"{base}/privacy.html"
    return {
        "ok": True,
        "platform": platform,
        "sku": sku_norm,
        "privacy_url": privacy_url or default_legal_url,
        "terms_url": terms_url or default_legal_url,
        "legal_version": _LEGAL_VERSION,
        "icp_number": _ICP_NUMBER,
        "app_filing_approved": _APP_FILING_APPROVED,
        "app_filing_beian_url": "https://beian.miit.gov.cn/",
        "app_filing_number": _APP_FILING_NUMBER,
        "min_android_version": release.min_version_code if release else 0,
        "latest_android_version": release.version_code if release else 0,
        "latest_android_version_name": release.version_name if release else "",
        "force_update": release.force_update if release else False,
        "update_available": release is not None,
        "apk_download_url": release.download_url if release else "",
        "apk_sha256": release.apk_sha256 if release else "",
        "apk_size": release.apk_size if release else 0,
        "release_source": release.source if release else "none",
        "apk_delta": _apk_delta(sku_norm, current_version_code, release),
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
