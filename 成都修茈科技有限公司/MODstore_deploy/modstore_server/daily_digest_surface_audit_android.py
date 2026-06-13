"""日更 digest · P-App 本地 Android 模拟器/真机 adb 截图（对齐 FHD run_android_surface_audit.mjs）。"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _android_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _fhd_root() -> Path:
    mono = (
        os.environ.get("XCMAX_MONOREPO_ROOT") or os.environ.get("MODSTORE_REPO_ROOT") or ""
    ).strip()
    if mono:
        p = Path(mono).expanduser().resolve() / "FHD"
        if p.is_dir():
            return p
    try:
        from modstore_server.daily_digest import _repo_root

        return Path(_repo_root()) / "FHD"
    except Exception:
        return Path(__file__).resolve().parents[3] / "FHD"


def _adb_bin() -> str:
    custom = (os.environ.get("SURFACE_AUDIT_ANDROID_ADB") or "").strip()
    if custom:
        return custom
    fhd = _fhd_root()
    bundled = fhd / "mobile-android" / ".toolchain" / "android-sdk" / "platform-tools" / "adb"
    if bundled.is_file():
        return str(bundled)
    return "adb"


def _adb_has_device(adb: str) -> bool:
    try:
        proc = subprocess.run(
            [adb, "devices"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        for line in (proc.stdout or "").splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                return True
    except Exception:
        logger.debug("android audit: adb devices failed", exc_info=True)
    return False


def _try_start_emulator() -> bool:
    if (os.environ.get("XCAGI_AUTO_START_EMULATOR", "1") or "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    fhd = _fhd_root()
    script = fhd / "scripts" / "dev" / "start_android_emulator.sh"
    if not script.is_file():
        return False
    try:
        subprocess.run(["bash", str(script)], cwd=str(fhd), check=False, timeout=180)
    except Exception:
        logger.warning("android audit: emulator start script failed", exc_info=True)
        return False
    return _adb_has_device(_adb_bin())


def _ensure_fhd_for_emulator() -> None:
    """模拟器 WebView 经 10.0.2.2 访问宿主机 FHD API。"""
    try:
        from modstore_server.surface_audit_deps import _ensure_fhd_api, _parse_port

        api_url = (
            os.environ.get("SURFACE_AUDIT_API_URL")
            or os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or "http://127.0.0.1:5000"
        )
        port = _parse_port(api_url.rstrip("/"), 5000)
        _ensure_fhd_api(port)
    except Exception:
        logger.warning("android audit: FHD API bootstrap failed", exc_info=True)


def _safe_slug(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", str(name or "")).strip()[:96] or "page"


def _filter_sample_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """sample 模式：优先 preview 页（与 surface_audit_pages P-App preview 对齐）。"""
    with_shot = [p for p in pages if isinstance(p, dict) and p.get("screenshot_b64")]
    if not with_shot:
        return pages[:1] if pages else []
    preview = [p for p in with_shot if p.get("preview")]
    if preview:
        return preview[:1]
    for pid in ("home_hub", "chat", "auth", "splash", "connect"):
        for p in with_shot:
            if str(p.get("id") or "") == pid:
                return [p]
    return with_shot[:1]


def _page_to_digest_row(
    page: Dict[str, Any],
    *,
    idx: int,
    save_root: Optional[Path],
) -> Dict[str, Any]:
    name = str(page.get("name") or page.get("id") or "App")
    route = str(page.get("android_route") or page.get("id") or "")
    b64 = str(page.get("screenshot_b64") or "").strip()
    save_path = ""
    err = str(page.get("error") or "").strip() or None
    if b64 and save_root is not None:
        slug = f"{idx:03d}_P-App_{_safe_slug(name)}"
        path = save_root / f"{slug}.png"
        try:
            path.write_bytes(base64.b64decode(b64))
            save_path = str(path)
        except Exception as exc:  # noqa: BLE001
            err = err or f"screenshot decode failed: {exc}"
    status = page.get("status")
    try:
        status_i = int(status) if status is not None else (200 if save_path else 0)
    except (TypeError, ValueError):
        status_i = 200 if save_path else 0
    return {
        "url": str(page.get("url") or f"xcagi://audit/nav/{route}"),
        "status": status_i,
        "title": name,
        "console_errors": list(page.get("console_errors") or [])[:8],
        "error": err,
        "screenshot_saved": save_path,
        "viewport": "mobile",
        "prepare": "",
        "lane": "P-App",
        "lane_label": "App P-App",
        "name": name,
        "android_capture": True,
        "native": bool(page.get("native")),
        "android_route": route,
    }


def run_android_surface_audit_sync(
    *,
    save_root: Optional[Path],
    sample: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """调用 FHD run_android_surface_audit.mjs；返回 (digest rows, meta)。"""
    if not _android_enabled():
        return [], {"skipped": True, "reason": "MODSTORE_SURFACE_AUDIT_ANDROID=0"}

    adb = _adb_bin()
    if not _adb_has_device(adb):
        if not _try_start_emulator():
            msg = "未检测到 Android 设备/模拟器（bash FHD/scripts/dev/start_android_emulator.sh）"
            return [], {"ok": False, "error": msg}
        adb = _adb_bin()

    _ensure_fhd_for_emulator()

    fhd = _fhd_root()
    script = fhd / "scripts" / "ci" / "run_android_surface_audit.mjs"
    if not script.is_file():
        return [], {"ok": False, "error": f"缺少 {script}"}

    api_port = 5000
    try:
        from modstore_server.surface_audit_deps import _parse_port

        api_url = (
            os.environ.get("SURFACE_AUDIT_API_URL")
            or os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or "http://127.0.0.1:5000"
        )
        api_port = _parse_port(api_url.rstrip("/"), 5000)
    except Exception:
        pass

    env = {**os.environ}
    env["SURFACE_AUDIT_ANDROID"] = "1"
    env["SURFACE_AUDIT_ANDROID_ADB"] = adb
    env.setdefault("SURFACE_AUDIT_PRODUCT_SKU", "enterprise")
    env.setdefault("SURFACE_AUDIT_INCLUDE_ENTERPRISE", "1")
    env.setdefault("SURFACE_AUDIT_ACCOUNT_KIND", "enterprise")
    env.setdefault("SURFACE_AUDIT_ANDROID_FHD_HOST", f"10.0.2.2:{api_port}")
    env.setdefault("SURFACE_AUDIT_API_URL", f"http://127.0.0.1:{api_port}")
    env.setdefault(
        "SURFACE_AUDIT_USER",
        os.environ.get("MODSTORE_SURFACE_AUDIT_USER") or "xcagi-enterprise-demo",
    )
    env.setdefault(
        "SURFACE_AUDIT_PASSWORD",
        os.environ.get("MODSTORE_SURFACE_AUDIT_PASSWORD") or "Demo@2026",
    )
    try:
        timeout = int(os.environ.get("SURFACE_AUDIT_ANDROID_TIMEOUT_MS", "600000"))
    except ValueError:
        timeout = 600_000
    timeout_sec = max(60, timeout // 1000)

    out_json: Path
    if save_root is not None:
        save_root.mkdir(parents=True, exist_ok=True)
        out_json = save_root / "android-audit.json"
    else:
        out_json = Path(tempfile.mkstemp(suffix=".json")[1])

    cmd = ["node", str(script), "--out", str(out_json)]
    logger.info("android audit: node %s (sample=%s adb=%s)", script.name, sample, adb)
    proc = subprocess.run(
        cmd,
        cwd=str(fhd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )

    payload: Dict[str, Any] = {}
    if out_json.is_file():
        try:
            payload = json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("android audit: invalid json at %s", out_json)
    if not payload and proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout.strip())
        except Exception:
            pass

    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    if sample and pages:
        pages = _filter_sample_pages(pages)

    meta: Dict[str, Any] = {
        "ok": bool(payload.get("success"))
        or any(isinstance(p, dict) and p.get("screenshot_b64") for p in pages),
        "source": payload.get("source") or "android-adb",
        "page_count": len(pages),
        "device_count": payload.get("device_count"),
        "message": payload.get("message") or "",
    }
    if proc.returncode != 0 and not meta["ok"]:
        meta["error"] = (
            payload.get("message")
            or (proc.stderr or proc.stdout or "")[:500]
            or f"android audit exit {proc.returncode}"
        )

    rows: List[Dict[str, Any]] = []
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        rows.append(_page_to_digest_row(page, idx=i, save_root=save_root))

    if _android_enabled() and not rows and meta.get("error"):
        rows.append(
            {
                "url": "xcagi://audit/nav/home_hub",
                "status": 0,
                "title": "Android 截图失败",
                "console_errors": [],
                "error": str(meta.get("error")),
                "screenshot_saved": "",
                "viewport": "mobile",
                "lane": "P-App",
                "lane_label": "App P-App",
                "name": "Android 截图失败",
                "android_capture": True,
            }
        )

    return rows, meta
