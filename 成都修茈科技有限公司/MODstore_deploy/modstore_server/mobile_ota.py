"""移动端 OTA 版本数据源（按平台：android / harmony / ios）。

发版闭环 ⑦：把"每平台最新版本"从裸 env 收敛到 ``download_release.json`` 的 ``mobile``
数据块，让闭环写数据即生效（免改 env + 重启）。env 仍作为覆盖/兜底，保持对旧
``XCAGI_ANDROID_*`` 配置向后兼容。

- android：versionCode 单调整数（当前 10）。
- harmony：versionCode 100000 制（10.0.0 → 100000）。
- ios：默认 available=False（无原生工程；走 App Store 非即时 OTA），有工程后置真值。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from modstore_server import download_release

PLATFORMS = ("android", "harmony", "ios")

_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "android": {"min_code": 10, "latest_code": 10, "latest_name": "10.0.0", "available": True},
    "harmony": {"min_code": 100000, "latest_code": 100000, "latest_name": "10.0.0", "available": True},
    "ios": {"min_code": 0, "latest_code": 0, "latest_name": "", "available": False},
}

_ARTIFACT_TPL = {
    "android": "XCAGI-{Sku}-Android-{name}.apk",
    "harmony": "XCAGI-{Sku}-Harmony-{name}.hap",
}


def _mobile_block(rel: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    r = rel if rel is not None else download_release.load_release()
    blk = r.get("mobile")
    return blk if isinstance(blk, dict) else {}


def _int_env(name: str) -> Optional[int]:
    v = (os.environ.get(name) or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _download_url(platform: str, name: str, sku: str) -> str:
    base = (os.environ.get("XCAGI_ANDROID_DOWNLOAD_BASE") or "https://xiu-ci.com").rstrip("/")
    if platform == "ios":
        return (os.environ.get("XCAGI_IOS_APPSTORE_URL") or "").strip()
    tpl = _ARTIFACT_TPL.get(platform)
    if not tpl or not name:
        return ""
    sku_seg = "enterprise" if sku == "enterprise" else "personal"
    fname = tpl.format(Sku=sku_seg.capitalize(), name=name)
    return f"{base}/download/{sku_seg}/{fname}"


def platform_release(
    platform: str,
    *,
    sku: str = "personal",
    rel: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """返回某平台 OTA 版本视图：min/latest code、latest_name、available、force_update、download_url。

    优先级：download_release.json#mobile.{platform} > env(android 兼容) > 内置默认。
    """
    p = (platform or "").strip().lower()
    if p not in PLATFORMS:
        p = "android"
    out: Dict[str, Any] = dict(_DEFAULTS[p])

    blk = _mobile_block(rel).get(p)
    if isinstance(blk, dict):
        if isinstance(blk.get("min_code"), int):
            out["min_code"] = blk["min_code"]
        if isinstance(blk.get("latest_code"), int):
            out["latest_code"] = blk["latest_code"]
        if blk.get("latest_name"):
            out["latest_name"] = str(blk["latest_name"])
        if "available" in blk:
            out["available"] = bool(blk["available"])
        if "force_update" in blk:
            out["force_update"] = bool(blk["force_update"])

    if p == "android":
        mc = _int_env("XCAGI_ANDROID_MIN_VERSION_CODE")
        if mc is not None:
            out["min_code"] = mc
        lc = _int_env("XCAGI_ANDROID_LATEST_VERSION_CODE")
        if lc is not None:
            out["latest_code"] = lc
        ln = (os.environ.get("XCAGI_ANDROID_LATEST_VERSION_NAME") or "").strip()
        if ln:
            out["latest_name"] = ln
        if (os.environ.get("XCAGI_ANDROID_FORCE_UPDATE") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            out["force_update"] = True

    out.setdefault("force_update", False)
    out["platform"] = p
    out["download_url"] = _download_url(p, str(out.get("latest_name") or ""), sku)
    return out


def set_platform_release(
    platform: str,
    *,
    latest_code: int,
    latest_name: str,
    min_code: Optional[int] = None,
    available: bool = True,
    force_update: Optional[bool] = None,
    path: Optional[Any] = None,
) -> Dict[str, Any]:
    """写某平台最新版本到 download_release.json#mobile（闭环⑦OTA 公告，写数据即生效）。

    返回 {ok, platform, mobile}。闭环回滚=用上一已知好版本再次调用本函数。
    """
    p = (platform or "").strip().lower()
    if p not in PLATFORMS:
        return {"ok": False, "error": f"unknown platform: {platform}"}
    rel = download_release.load_release(path=path)
    mobile = rel.get("mobile")
    if not isinstance(mobile, dict):
        mobile = {}
    entry = mobile.get(p) if isinstance(mobile.get(p), dict) else {}
    entry = dict(entry)
    entry["latest_code"] = int(latest_code)
    entry["latest_name"] = str(latest_name)
    if min_code is not None:
        entry["min_code"] = int(min_code)
    entry["available"] = bool(available)
    if force_update is not None:
        entry["force_update"] = bool(force_update)
    mobile[p] = entry
    rel["mobile"] = mobile
    download_release.save_release(rel, path=path)
    try:
        download_release.write_public_manifests(rel)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "platform": p, "mobile": entry}
