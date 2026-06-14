"""P-App / P-W / P-S 表面巡检：Playwright 截页面 + 本地缓存 + API 输出。"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_FHD_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _FHD_ROOT / "config" / "surface_audit_pages.json"
_SCRIPT_PATH = _FHD_ROOT / "scripts" / "ci" / "run_surface_audit.mjs"
_CACHE_DIR = _FHD_ROOT / "data" / "surface_audit"
_NODE_MODULES = _FHD_ROOT / "frontend" / "node_modules"

# 今日缓存缺失时，回退到此窗口内最近一天的缓存（磁盘 PNG 仍在）。
_CACHE_FALLBACK_MAX_AGE_DAYS = int(os.environ.get("SURFACE_AUDIT_CACHE_FALLBACK_DAYS", "14"))
_DATE_JSON_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def _today_key() -> str:
    return date.today().isoformat()


def _lane_cache_dir(lane: str) -> Path:
    return _CACHE_DIR / lane.replace("/", "_")


def _lane_png_root(lane: str) -> Path:
    return _CACHE_DIR / "png" / lane.replace("/", "_")


def _lane_png_day_dirs(lane: str) -> list[Path]:
    """按日期从新到旧列出 lane 的 PNG 目录（与 JSON 缓存回退窗口一致）。"""
    root = _lane_png_root(lane)
    if not root.is_dir():
        return []
    today = _today_key()
    floor = ""
    try:
        floor = (
            date.fromisoformat(today) - timedelta(days=_CACHE_FALLBACK_MAX_AGE_DAYS)
        ).isoformat()
    except ValueError:
        floor = ""
    ranked: list[tuple[str, Path]] = []
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        matched = _DATE_JSON_RE.match(f"{candidate.name}.json")
        if not matched:
            continue
        day = matched.group(1)
        if day > today:
            continue
        if floor and day < floor:
            continue
        ranked.append((day, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in ranked]


def _page_png_slug(index: int, page: dict[str, Any]) -> str:
    page_id = str(page.get("id") or page.get("name") or "page").strip()
    slug = f"{index:03d}_{page_id}"
    return re.sub(r"[^\w.-]+", "-", slug)


def resolve_lane_page_png_path(
    lane: str,
    index: int,
    page: dict[str, Any] | None,
) -> Path | None:
    """解析单页 PNG：优先 JSON 内路径，再按 id 匹配历史日目录，最后按序号回退。"""
    page = page if isinstance(page, dict) else {}
    saved = str(page.get("screenshot_saved") or "").strip()
    if saved:
        png_path = Path(saved)
        if png_path.is_file():
            return png_path

    slug = _page_png_slug(index, page)
    for day_dir in _lane_png_day_dirs(lane):
        candidate = day_dir / f"{slug}.png"
        if candidate.is_file():
            return candidate

    for day_dir in _lane_png_day_dirs(lane):
        pngs = sorted(day_dir.glob("*.png"))
        if 0 <= index < len(pngs):
            return pngs[index]
    return None


def _cache_file(lane: str) -> Path:
    return _lane_cache_dir(lane) / f"{_today_key()}.json"


def _load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {"lanes": {}}
    return cast("dict[str, Any]", json.loads(_CONFIG_PATH.read_text(encoding="utf-8")))


def _read_cache_path(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("success") else None
    except RECOVERABLE_ERRORS:
        logger.debug("surface audit cache read failed: %s", path, exc_info=True)
        return None


def _most_recent_prior_cache(lane: str) -> Path | None:
    """今日缓存缺失时，挑窗口内最近一天的缓存。

    避免本地巡检 lane（P-App / P-S）在每次终端/截图请求时重跑 Playwright
    （无 adb 设备会退化为不可服务的占位，前端表现为黑屏破图）。
    """
    cache_dir = _lane_cache_dir(lane)
    if not cache_dir.is_dir():
        return None
    today = _today_key()
    floor = ""
    try:
        floor = (
            date.fromisoformat(today) - timedelta(days=_CACHE_FALLBACK_MAX_AGE_DAYS)
        ).isoformat()
    except ValueError:
        floor = ""
    best: tuple[str, Path] | None = None
    for candidate in cache_dir.glob("*.json"):
        matched = _DATE_JSON_RE.match(candidate.name)
        if not matched:
            continue
        day = matched.group(1)
        if day >= today:  # 今日/未来另行处理
            continue
        if floor and day < floor:
            continue
        if best is None or day > best[0]:
            best = (day, candidate)
    return best[1] if best else None


def _read_cache(lane: str) -> dict[str, Any] | None:
    return _read_cache_path(_cache_file(lane))


def _write_cache(lane: str, payload: dict[str, Any]) -> None:
    path = _cache_file(lane)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _adb_has_device() -> bool:
    adb = _FHD_ROOT / "mobile-android" / ".toolchain" / "android-sdk" / "platform-tools" / "adb"
    if not adb.is_file():
        return False
    try:
        proc = subprocess.run(
            [str(adb), "devices"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        for line in (proc.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return True
    except RECOVERABLE_ERRORS:
        return False
    return False


def _node_env(lane: str = "") -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("SURFACE_AUDIT_BASE_URL", "http://127.0.0.1:5001")
    env.setdefault("SURFACE_AUDIT_API_URL", "http://127.0.0.1:5000")
    env.setdefault(
        "SURFACE_AUDIT_ADMIN_BASE_URL",
        env.get("SURFACE_AUDIT_ADMIN_BASE_URL")
        or env.get("SURFACE_AUDIT_API_URL")
        or "http://127.0.0.1:5000",
    )
    env.setdefault(
        "SURFACE_AUDIT_MARKETING_BASE_URL",
        os.environ.get("SURFACE_AUDIT_MARKETING_BASE_URL")
        or os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL")
        or "https://xiu-ci.com",
    )
    env.setdefault(
        "XCAGI_MARKET_BASE_URL", env.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:5176"
    )
    lane_key = (lane or "").strip()
    if lane_key == "P-W":
        marketing = (
            env.get("SURFACE_AUDIT_MARKETING_BASE_URL")
            or os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL")
            or "https://xiu-ci.com"
        ).rstrip("/")
        # 上方 setdefault 已填入 127.0.0.1 本地默认值，这里须按「进程环境是否显式
        # 配置」判断覆盖，否则 P-W 刷新会打到本地不存在的 5000/5176 端口。
        if not os.environ.get("SURFACE_AUDIT_ADMIN_BASE_URL"):
            env["SURFACE_AUDIT_ADMIN_BASE_URL"] = marketing
        if not os.environ.get("XCAGI_MARKET_BASE_URL"):
            env["XCAGI_MARKET_BASE_URL"] = marketing
        if not os.environ.get("SURFACE_AUDIT_API_URL"):
            env["SURFACE_AUDIT_API_URL"] = marketing
    if lane_key in ("P-S", "P-App"):
        env["SURFACE_AUDIT_PRODUCT_SKU"] = "enterprise"
        env["SURFACE_AUDIT_INCLUDE_ENTERPRISE"] = "1"
        env["SURFACE_AUDIT_ACCOUNT_KIND"] = "enterprise"
        if lane_key == "P-App":
            env.setdefault("SURFACE_AUDIT_ANDROID_PACKAGE", "com.xiuci.xcagi.mobile.enterprise")
            # 模拟器上 adb root + iptables 会短暂断开 adb，导致 screencap 全失败
            env.setdefault("SURFACE_AUDIT_SKIP_FORCE_UPDATE", "0")
        if not env.get("SURFACE_AUDIT_USER"):
            try:
                from app.application.surface_audit_demo_account import demo_password, demo_username

                env["SURFACE_AUDIT_USER"] = demo_username()
                env["SURFACE_AUDIT_PASSWORD"] = demo_password()
            except RECOVERABLE_ERRORS:
                env.setdefault("SURFACE_AUDIT_USER", "xcagi-enterprise-demo")
                env.setdefault("SURFACE_AUDIT_PASSWORD", "Demo@2026")
    elif lane_key != "P-W":
        env.setdefault("SURFACE_AUDIT_PRODUCT_SKU", "personal")
    if (
        env.get("SURFACE_AUDIT_ANDROID", "").strip() == ""
        and env.get("XCAGI_SURFACE_AUDIT_ANDROID", "").strip() == ""
    ):
        if _adb_has_device():
            env["SURFACE_AUDIT_ANDROID"] = "1"
    elif os.environ.get("SURFACE_AUDIT_ANDROID") or os.environ.get("XCAGI_SURFACE_AUDIT_ANDROID"):
        env.setdefault("SURFACE_AUDIT_ANDROID", "1")
    node_path = str(_NODE_MODULES)
    if _NODE_MODULES.is_dir():
        env["NODE_PATH"] = node_path + (
            os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else ""
        )
        env["PATH"] = str(_FHD_ROOT / "frontend" / "node_modules" / ".bin") + (
            os.pathsep + env["PATH"] if env.get("PATH") else ""
        )
    return env


def _playwright_available() -> bool:
    pw = _NODE_MODULES / "@playwright" / "test"
    return _SCRIPT_PATH.is_file() and pw.is_dir()


def run_surface_audit_lane(lane: str, *, refresh: bool = False) -> dict[str, Any]:
    """执行或读取 lane 巡检结果。lane 例：P-App / P-W / P-S。"""
    lane = (lane or "").strip()
    if not lane:
        return {"success": False, "message": "lane 必填"}

    cfg = _load_config()
    if lane not in (cfg.get("lanes") or {}):
        return {"success": False, "message": f"未知 lane: {lane}"}

    if not refresh:
        cached = _read_cache(lane)
        if cached:
            cached["from_cache"] = True
            return cached

    if not _playwright_available():
        return {
            "success": False,
            "message": "Playwright 未安装：请在 FHD/frontend 执行 npm ci && npx playwright install chromium",
            "lane": lane,
        }

    out_path = _cache_file(lane)
    cmd = [
        "node",
        str(_SCRIPT_PATH),
        lane,
        "--refresh",
        "--out",
        str(out_path),
    ]
    # P-W 全量 60+ 远程页（含 catalog 动态扩展），600s 不够
    default_timeout = "1200" if lane == "P-W" else "600"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_FHD_ROOT),
            env=_node_env(lane),
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("SURFACE_AUDIT_TIMEOUT_SEC", default_timeout)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"巡检超时（lane={lane}）", "lane": lane}
    except FileNotFoundError:
        return {"success": False, "message": "未找到 node 可执行文件", "lane": lane}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:2000]
        logger.warning("surface audit failed lane=%s rc=%s err=%s", lane, proc.returncode, err)
        return {"success": False, "message": err or "Playwright 巡检失败", "lane": lane}

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        if out_path.is_file():
            payload = json.loads(out_path.read_text(encoding="utf-8"))
        else:
            return {"success": False, "message": "巡检输出非 JSON", "lane": lane}

    if payload.get("success"):
        payload["from_cache"] = False
        payload["cached_at"] = datetime.now(UTC).isoformat()
        _write_cache(lane, payload)
    return cast("dict[str, Any]", payload)


def get_surface_audit_lane(lane: str, *, refresh: bool = False) -> dict[str, Any]:
    """API 友好封装：返回 {success, data}。"""
    raw = run_surface_audit_lane(lane, refresh=refresh)
    if not raw.get("success"):
        return raw
    data = {k: v for k, v in raw.items() if k != "success"}
    return {"success": True, "data": data}


def list_configured_lanes() -> list[str]:
    return list((_load_config().get("lanes") or {}).keys())
