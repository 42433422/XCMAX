"""每日摘要 · 三端页面截图巡检（P-W 网站 / P-S 软件 / P-App 移动 App 面）。

Playwright 抓取关键 URL 全页截图，记录 HTTP 状态与 console error，供邮件段落与 Vibe 预备引用。

环境变量：
- ``MODSTORE_DAILY_SURFACE_AUDIT_ENABLED``（默认 ``1``）：设为 ``0`` 关闭本段落。
- ``MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL``：站点根（默认 ``https://xiu-ci.com``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS``（默认 ``45000``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR``：可选，保存 PNG 目录（默认 ``playwright-report/digest-surfaces`` 相对仓库根）。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED``（默认 ``1``）：是否对每条产线截图调用 bench LLM 生成「对应员工」的现状 / 异常 / 改进建议分析；未配置 bench LLM 时回退到基于 HTTP / console 的规则化摘要。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID``：分析调用 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_SURFACE_AUDIT_USER`` / ``MODSTORE_SURFACE_AUDIT_PASSWORD``：AI 市场 SPA 截图前登录（默认 ``admin`` / ``admin123``）。
- ``MODSTORE_SURFACE_AUDIT_API_URL``：登录 API 根（默认 ``MODSTORE_INTERNAL_API_BASE`` 或站点 ``base_url``）。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DESKTOP_VIEWPORT = {"width": 1280, "height": 720}
_MOBILE_VIEWPORT = {"width": 390, "height": 844}


@dataclass(frozen=True)
class SurfaceTarget:
    lane: str
    lane_label: str
    name: str
    path: str
    viewport: str  # desktop | mobile
    prepare: str = ""
    base: str = ""  # 空=用全局 _base_url()（xiu-ci.com）；P-S 本地企业版指向 5001


_STATIC_PW_PAGES: Tuple[Tuple[str, str], ...] = (
    ("官网首页", "/"),
    ("关于修茈", "/about.html"),
    ("产品中心", "/services.html"),
    ("解决方案", "/solutions.html"),
    ("客户案例", "/cases.html"),
    ("制造案例", "/case-manufacture.html"),
    ("教育案例", "/case-edu.html"),
    ("园区案例", "/case-park.html"),
    ("新闻资讯", "/news.html"),
    ("资质荣誉", "/honors.html"),
    ("联系我们", "/contact.html"),
    # /developer.html 和 /excel-to-ai.html 已确认服务器返回首页内容（title/innerText 与 index.html 完全相同）→ 移除
)

_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = (("软件下载", "/market/workbench/download"),)
_PW_MARKET_ADMIN_PAGES: Tuple[Tuple[str, str], ...] = (
    ("管理端·数据库管理", "/market/admin/database"),
    ("管理端·值班员工", "/market/admin/duty-employees"),
    ("管理端·运维审计", "/market/admin/ops-audit"),
    ("管理端·员工自主决策", "/market/admin/employee-autonomy"),
    ("管理端·变更请求", "/market/admin/change-requests"),
    ("管理端·员工入职", "/market/admin/yuangon-onboard"),
    ("管理端·编排任务", "/market/admin/orchestrate-jobs"),
    ("管理端·客服审核", "/market/admin/customer-service"),
    ("管理端·管家技能", "/market/admin/butler-skills"),
    ("管理端·AI 账号池", "/market/admin/ai-accounts"),
)
_PW_WB_MODE_PAGES: Tuple[Tuple[str, str], ...] = (
    ("工作台·聊", "/market/workbench/home", "direct"),
    ("工作台·做", "/market/workbench/home", "make"),
    ("工作台·说", "/market/workbench/home", "voice"),
)

_PW_SIDEBAR_PAGES: Tuple[Tuple[str, str], ...] = (
    ("AI 客服", "/market/customer-service"),
    ("沙箱测试", "/market/ai-test/sandbox"),  # /market/sandbox 是客户端重定向，用规范路径
)


_PS_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("会员方案", "/market/plans"),
    ("登录页", "/market/login"),
    ("注册页", "/market/register"),
)

_PAPP_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("市场落地页（移动）", "/market/about"),
    ("软件下载（移动）", "/market/workbench/download"),
)

# P-S 软件（本地企业版客户端 · 127.0.0.1:5001）：与 FHD config/surface_audit_pages.json
# 的 P-S lane 同源（enterprise SKU），让邮件「三端」P-S 栏不再为空。
_PS_DESKTOP_PAGES: Tuple[Tuple[str, str], ...] = (
    ("智能对话", "/"),
    ("智能生态", "/ai-ecosystem"),
    ("产品管理", "/products"),
    ("客户管理", "/customers"),
    ("订单管理", "/orders"),
    ("出货记录", "/shipment-records"),
    ("审批中心", "/approval-hub/workspace"),
    ("库存管理", "/inventory"),
    ("MODstore", "/mod-store"),
    ("设置", "/settings"),
    ("桥接控制台", "/console"),
    ("批量分析", "/batch-analyze"),
    ("规划桥 Mod", "/mod/xcagi-planner-bridge/chat"),
)

_AI_STORE_TABS: Tuple[Tuple[str, str], ...] = (
    ("AI市场-全部商品", "all"),
    ("AI市场-宿主基础员工", "host_foundation"),
    ("AI市场-办公员工包", "office"),
    ("AI市场-工作流员工", "workflow"),
    ("AI市场-AI员工", "ai_employee"),
)

_AI_STORE_TAB_LABELS: Dict[str, str] = {
    "all": "全部商品",
    "host_foundation": "宿主基础员工",
    "office": "办公员工包",
    "workflow": "工作流员工",
    "ai_employee": "AI 员工",
}
_PW_AI_MARKET_EXTRA_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("AI市场-高级筛选", "/market/ai-store", "ai_store_tab:all|filters_open"),
    ("钱包", "/market/wallet", ""),
    ("已购商品", "/market/wallet/purchased", ""),
    ("订单列表", "/market/orders", ""),
)

# 账户/通知/AI考试 — 登录后有侧栏/用户菜单直接入口
_PW_ACCOUNT_PAGES: Tuple[Tuple[str, str], ...] = (
    ("账户设置", "/market/account"),
    ("通知中心", "/market/notifications"),
    ("使用统计", "/market/analytics"),
    ("退款申请", "/market/refunds"),
    ("开发者门户", "/market/dev"),
)

# AI 考试独立 Tab（AiTestLayout 下 Tab 栏）
_PW_AI_TEST_PAGES: Tuple[Tuple[str, str], ...] = (("AI员工考试", "/market/ai-test/exam"),)

# 工作台核心子页（WorkbenchView 顶栏有直接入口）
_PW_WORKBENCH_PAGES: Tuple[Tuple[str, str], ...] = (
    ("统一工作台", "/market/workbench/unified"),
    ("我的员工", "/market/workbench/employees"),
    ("我的素材", "/market/workbench/materials"),
    ("脚本工作流", "/market/workbench/script-workflows"),
)


def _base_url() -> str:
    raw = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com").strip()
    return raw.rstrip("/")


def _ps_base_url() -> str:
    """P-S 软件（本地企业版客户端）基址。

    与 FHD ``surface_audit_service`` 同口径：默认 ``http://127.0.0.1:5001``，
    可用 ``MODSTORE_SURFACE_AUDIT_PS_BASE_URL`` 覆盖（生产可指向可达的企业版宿主）。
    """
    raw = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_PS_BASE_URL")
        or os.environ.get("SURFACE_AUDIT_BASE_URL")
        or "http://127.0.0.1:5001"
    ).strip()
    return raw.rstrip("/")


def _ps_audit_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _safe_slug_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", str(name or "")).strip()[:96] or "page"


def _fetch_market_catalog_sync(base: str) -> List[Dict[str, Any]]:
    """拉取 AI 市场公开目录（用于 /market/catalog/:id 截图）。"""
    items: List[Dict[str, Any]] = []
    internal = (
        (os.environ.get("MODSTORE_INTERNAL_API_BASE") or "http://127.0.0.1:9990")
        .strip()
        .rstrip("/")
    )
    bases: List[str] = []
    for candidate in (internal, base.rstrip("/")):
        if candidate and candidate not in bases:
            bases.append(candidate)

    for api_base in bases:
        url = f"{api_base}/api/market/catalog"
        seen = 0
        batch_items: List[Dict[str, Any]] = []
        while url and seen < 20:
            seen += 1
            req = urllib.request.Request(url, headers={"User-Agent": "MODstore-surface-audit/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                logger.warning("surface audit: catalog fetch failed base=%s: %s", api_base, exc)
                batch_items = []
                break
            if isinstance(payload, dict):
                batch = payload.get("items")
                if isinstance(batch, list):
                    batch_items.extend(x for x in batch if isinstance(x, dict))
                url = str(payload.get("next") or "").strip()
            else:
                break
        if batch_items:
            items = batch_items
            break
    return items


def build_surface_targets() -> List[SurfaceTarget]:
    """全量：P-W 营销静态 + AI 市场 Tab/筛选/钱包/订单 + 全部 catalog 详情。"""
    base = _base_url()
    catalog: List[Dict[str, Any]] = []
    if (os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "0") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        pass  # 默认跳过逐商品截图
    else:
        catalog = _fetch_market_catalog_sync(base)
    out: List[SurfaceTarget] = []

    for name, path in _STATIC_PW_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_MARKET_ENTRY_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PS_PUBLIC_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for tab_name, tab_id in _AI_STORE_TABS:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                tab_name,
                "/market/ai-store",
                "desktop",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )

    for name, path, prepare in _PW_AI_MARKET_EXTRA_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare=prepare or None,
            )
        )

    for item in catalog:
        cid = item.get("id")
        if cid is None:
            continue
        label = str(item.get("name") or item.get("pkg_id") or cid).strip()
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                f"AI商品-{label}",
                f"/market/catalog/{cid}",
                "desktop",
            )
        )

    for name, path, mode in _PW_WB_MODE_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare=f"wb_mode:{mode}",
            )
        )

    for name, path in _PW_SIDEBAR_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_WORKBENCH_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_AI_TEST_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_ACCOUNT_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_MARKET_ADMIN_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare="admin_digest",
            )
        )

    if _ps_audit_enabled():
        ps_base = _ps_base_url()
        for name, path in _PS_DESKTOP_PAGES:
            out.append(
                SurfaceTarget("P-S", "软件 P-S", name, path, "desktop", base=ps_base)
            )

    for name, path in _PAPP_PUBLIC_PAGES:
        out.append(SurfaceTarget("P-App", "App P-App", name, path, "mobile"))

    for tab_name, tab_id in _AI_STORE_TABS:
        out.append(
            SurfaceTarget(
                "P-App",
                "App P-App",
                f"{tab_name}（移动）",
                "/market/ai-store",
                "mobile",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )

    return out


def default_surface_targets() -> List[SurfaceTarget]:
    """P-W / P-S / P-App 巡检目标（营销 + AI 市场全链路 + catalog 详情）。"""
    return build_surface_targets()


def _repo_root() -> Path:
    try:
        from modstore_server.daily_digest import _repo_root as root_fn

        return Path(root_fn())
    except Exception:
        return Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()


def _png_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


def compute_surface_baseline_delta(
    day: str,
    results: List[Dict[str, Any]],
    *,
    save_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compare today's PNG fingerprints vs previous calendar day (file hash)."""
    root = save_root if save_root is not None else _save_dir(day)
    if root is None:
        return {"ok": True, "skipped": True, "reason": "no save dir", "rows": []}

    prev_day = (
        datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    prev_root = root.parent / prev_day
    rows: List[Dict[str, Any]] = []
    changed = 0
    for r in results:
        saved = str(r.get("screenshot_saved") or "").strip()
        if not saved:
            continue
        cur = Path(saved)
        prev = prev_root / cur.name
        cur_fp = _png_fingerprint(cur)
        prev_fp = _png_fingerprint(prev) if prev.is_file() else ""
        delta = "new" if not prev_fp else ("same" if cur_fp == prev_fp else "changed")
        if delta == "changed":
            changed += 1
        rows.append(
            {
                "name": r.get("name"),
                "lane": r.get("lane"),
                "delta": delta,
                "fingerprint": cur_fp,
                "prev_fingerprint": prev_fp,
            }
        )
    return {
        "ok": True,
        "skipped": False,
        "day": day,
        "prev_day": prev_day,
        "changed_count": changed,
        "rows": rows,
    }


def baseline_delta_excerpt_markdown(delta: Dict[str, Any]) -> str:
    if delta.get("skipped"):
        return "（相对昨日 Δ：未保存截图目录，跳过）"
    rows = delta.get("rows") if isinstance(delta.get("rows"), list) else []
    if not rows:
        return "（相对昨日 Δ：无截图可对比）"
    parts: List[str] = []
    for row in rows:
        flag = row.get("delta") or "?"
        sym = {"same": "＝", "changed": "≠", "new": "＋"}.get(str(flag), "?")
        parts.append(f"{sym} {row.get('name')} ({flag})")
    summary = f"变更 {delta.get('changed_count', 0)} 页"
    return f"**相对昨日 Δ** · {summary}\n" + "\n".join(parts)


def _save_dir(day: str) -> Optional[Path]:
    raw = (
        os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR")
        or "playwright-report/digest-surfaces"
    ).strip()
    if not raw or raw.lower() in ("0", "false", "no", "off", "none"):
        return None
    out = _repo_root() / raw / day
    out.mkdir(parents=True, exist_ok=True)
    return out


_MARKET_AUTH_SKIP_PREFIXES: Tuple[str, ...] = (
    "/market/login",
    "/market/register",
    "/market/login-email",
    "/market/forgot-password",
)


def _path_needs_market_auth(path: str) -> bool:
    """除登录/注册外，/market/* SPA 页注入 modstore_token（workbench/download 等需登录）。"""
    p = str(path or "").strip()
    if not p.startswith("/market"):
        return False
    for skip in _MARKET_AUTH_SKIP_PREFIXES:
        if p == skip or p.startswith(skip + "/") or p.startswith(skip + "?"):
            return False
    return True


def _parse_set_cookie_headers(headers: Any) -> Dict[str, str]:
    jar: Dict[str, str] = {}
    raw_lines: List[str] = []
    if headers is None:
        return jar
    if hasattr(headers, "get_all"):
        try:
            raw_lines = list(headers.get_all("Set-Cookie") or [])
        except Exception:
            raw_lines = []
    if not raw_lines:
        one = headers.get("Set-Cookie") if hasattr(headers, "get") else None
        if one:
            raw_lines = [one] if isinstance(one, str) else list(one)
    for line in raw_lines:
        part = str(line).split(";")[0]
        idx = part.find("=")
        if idx > 0:
            jar[part[:idx].strip()] = part[idx + 1 :].strip()
    return jar


def _login_surface_audit_sync() -> Dict[str, str]:
    """Playwright 截图前登录 MODstore，写入 modstore_token（对齐 FHD surface_audit_auth.mjs）。"""
    api_base = (
        (
            os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or os.environ.get("MODSTORE_INTERNAL_API_BASE")
            or _base_url()
        )
        .strip()
        .rstrip("/")
    )
    user = (os.environ.get("MODSTORE_SURFACE_AUDIT_USER") or "admin").strip()
    password = (os.environ.get("MODSTORE_SURFACE_AUDIT_PASSWORD") or "admin123").strip()
    account_kind = (os.environ.get("MODSTORE_SURFACE_AUDIT_ACCOUNT_KIND") or "admin").strip()

    cookies: Dict[str, str] = {}

    def _req(
        url: str, payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        headers = {"User-Agent": "MODstore-surface-audit/1.0", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            csrf = cookies.get("csrf_token") or ""
            if csrf:
                headers["X-CSRF-Token"] = csrf
            cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
            if cookie_hdr:
                headers["Cookie"] = cookie_hdr
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        else:
            req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            cookies.update(_parse_set_cookie_headers(resp.headers))
            return body, cookies

    try:
        _req(f"{api_base}/api/health")
        web, _ = _req(
            f"{api_base}/api/auth/login",
            {"username": user, "password": password, "account_kind": account_kind},
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("surface audit: market login failed base=%s err=%s", api_base, exc)
        return {}

    ok = bool(web.get("ok") or web.get("success"))
    access = str(web.get("access_token") or web.get("token") or "").strip()
    refresh = str(web.get("refresh_token") or "").strip()
    if not ok or not access:
        logger.warning(
            "surface audit: market login rejected base=%s msg=%s",
            api_base,
            web.get("message") or web.get("error") or "no access_token",
        )
        return {}
    return {"access_token": access, "refresh_token": refresh, "username": user}


def _fetch_admin_digest_code_sync(auth: Dict[str, str]) -> str:
    """从 MODstore API 拉取管理端 6 位校验码（对齐 FHD digest-identity 自签发）。"""
    api_base = (
        (
            os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or os.environ.get("MODSTORE_INTERNAL_API_BASE")
            or "http://127.0.0.1:9990"
        )
        .strip()
        .rstrip("/")
    )
    headers = {"Accept": "application/json", "User-Agent": "MODstore-surface-audit/1.0"}
    token = str(auth.get("access_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    csrf = str(auth.get("csrf_token") or "").strip()
    if csrf:
        headers["X-CSRF-Token"] = csrf
    try:
        req = urllib.request.Request(
            f"{api_base}/api/xcmax/admin/digest-identity", headers=headers, method="GET"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        code = str(data.get("code") or "").strip().upper()
        if len(code) == 6:
            return code
    except Exception as exc:
        logger.warning("surface audit: digest-identity fetch failed: %s", exc)
    return ""


async def _inject_admin_digest(context: Any, code: str) -> None:
    c = str(code or "").strip().upper()
    if not c:
        return
    payload = json.dumps({"code": c, "ts": int(__import__("time").time() * 1000)})
    script = (
        "(function(){try{localStorage.setItem('xcmax_digest_identity_code',"
        + json.dumps(payload)
        + ");}catch(e){}})();"
    )
    await context.add_init_script(script)


async def _prepare_admin_digest(context: Any, auth: Dict[str, str]) -> None:
    code = _fetch_admin_digest_code_sync(auth)
    if code:
        try:
            api_base = (
                (
                    os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
                    or os.environ.get("MODSTORE_INTERNAL_API_BASE")
                    or "http://127.0.0.1:9990"
                )
                .strip()
                .rstrip("/")
            )
            payload = json.dumps({"code": code}).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            csrf = str(auth.get("csrf_token") or "").strip()
            if csrf:
                headers["X-CSRF-Token"] = csrf
            req = urllib.request.Request(
                f"{api_base}/api/auth/verify-admin-digest-code",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30):
                pass
        except Exception as exc:
            logger.warning("surface audit: verify-admin-digest-code failed: %s", exc)
    await _inject_admin_digest(context, code)


async def _inject_market_auth(context: Any, auth: Dict[str, str]) -> None:
    access = str(auth.get("access_token") or "").strip()
    if not access:
        return
    refresh = str(auth.get("refresh_token") or "").strip()
    script = (
        "(function(){"
        f"localStorage.setItem('modstore_token', {json.dumps(access)});"
        + (
            f"localStorage.setItem('modstore_refresh_token', {json.dumps(refresh)});"
            if refresh
            else ""
        )
        + "})();"
    )
    await context.add_init_script(script)


async def _wait_page_ready(page: Any, *, timeout_ms: int) -> None:
    """等待 SPA/静态页渲染与中文字体就绪，避免截图文字丢失。"""
    try:
        await page.add_style_tag(
            content=(
                '@import url("https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&display=swap");'
                '*{font-family:"Noto Sans SC","WenQuanYi Micro Hei","DejaVu Sans",sans-serif!important}'
            )
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 25_000))
    except Exception:
        pass
    try:
        await page.evaluate(
            "() => (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve()"
        )
    except Exception:
        pass
    await page.wait_for_timeout(1500)


async def _apply_page_prepare(page: Any, prepare: str, timeout_ms: int) -> None:
    for step in [s.strip() for s in str(prepare or "").split("|") if s.strip()]:
        await _apply_page_prepare_step(page, step, timeout_ms)


async def _apply_page_prepare_step(page: Any, prepare: str, timeout_ms: int) -> None:
    if prepare == "admin_digest":
        try:
            unlock_btn = page.get_by_role("button", name=re.compile("解锁管理端"))
            if await unlock_btn.is_visible(timeout=2500):
                await unlock_btn.click(timeout=5000)
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        try:
            await page.wait_for_selector(".wb-sidebar-admin-nav, #app .app-shell", timeout=12_000)
        except Exception:
            pass
        return
    if prepare.startswith("wb_mode:"):
        mode = prepare.split(":", 1)[1]
        labels = {"direct": "聊", "make": "做", "voice": "说"}
        label = labels.get(mode, "")
        if label:
            btn = page.locator(".wb-sidebar-modes button.wb-sidebar-mode-btn").filter(
                has_text=label
            )
            await btn.first.click(timeout=min(timeout_ms, 20_000))
            await page.wait_for_timeout(800)
        return
    if prepare.startswith("ai_store_tab:"):
        tab_id = prepare.split(":", 1)[1]
        label = _AI_STORE_TAB_LABELS.get(tab_id, "")
        if not label:
            return
        btn = page.locator("button.store-nav__item").filter(has_text=label)
        await btn.first.click(timeout=min(timeout_ms, 20_000))
        await page.wait_for_timeout(1200)
        return
    if prepare == "filters_open":
        try:
            btn = page.locator(".store-adv-toggle").filter(has_text="高级筛选")
            await btn.first.click(timeout=min(timeout_ms, 15_000))
            await page.wait_for_selector(".store-adv-filters", state="visible", timeout=6000)
            await page.wait_for_timeout(600)
        except Exception:
            pass
        return


async def _capture_one(
    page: Any,
    *,
    url: str,
    viewport: str,
    timeout_ms: int,
    save_path: Optional[Path],
    prepare: str = "",
) -> Dict[str, Any]:
    console_errors: List[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(str(msg.text)) if msg.type == "error" else None,
    )
    vp = _MOBILE_VIEWPORT if viewport == "mobile" else _DESKTOP_VIEWPORT
    await page.set_viewport_size(vp)
    status: Optional[int] = None
    title = ""
    err: Optional[str] = None
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status = resp.status if resp else None
        await _wait_page_ready(page, timeout_ms=timeout_ms)
        if prepare:
            await _apply_page_prepare(page, prepare, timeout_ms)
        title = await page.title()
        png = await page.screenshot(full_page=False, type="png")
        if save_path is not None:
            save_path.write_bytes(png)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        png = b""
    return {
        "url": url,
        "status": status,
        "title": title,
        "console_errors": console_errors[:8],
        "error": err,
        "screenshot_saved": str(save_path) if save_path and save_path.is_file() else "",
        "viewport": viewport,
        "prepare": prepare or "",
    }


# ─── 三端 lane → 对应在岗员工 ───────────────────────────────────────────────
#
# 与 ``duty_roster.SIX_LINE_DEPARTMENTS`` 对齐：
# - P-W   → ``prod_web``（网站部）关键子区：营销静态 / 市场 SPA / 文档 SEO
# - P-S   → ``prod_software``（软件部）关键子区：核心编码 / 测试 / 编排
# - P-App → 移动发布官 + 市场前端（移动端 WebView 由 market SPA 复用）
_LANE_OWNER_FALLBACK: Dict[str, List[str]] = {
    "P-W": [
        "site-content-editor",
        "marketing-site-builder",
        "seo-sitemap-curator",
        "market-frontend-dev",
    ],
    "P-S": [
        "fhd-core-maintainer",
        "vibe-coding-maintainer",
        "test-qa-runner",
        "market-frontend-dev",
    ],
    "P-App": [
        "mobile-android-release-officer",
        "mobile-ios-release-officer",
        "market-frontend-dev",
    ],
}

_LANE_TO_DEPARTMENT = {"P-W": "prod_web", "P-S": "prod_software"}


def lane_employee_ids(lane: str, *, limit: int = 6) -> List[str]:
    """三端 lane 对应的在岗员工 pkg_id 列表（去重，保持顺序）。

    优先从 :data:`duty_roster.SIX_LINE_DEPARTMENTS` 解析对应部门所有子区员工；
    解析失败或 P-App（无独立部门）回退到 :data:`_LANE_OWNER_FALLBACK`。
    """
    out: List[str] = []

    def _push(pid: str) -> None:
        pid = str(pid or "").strip()
        if pid and pid not in out:
            out.append(pid)

    dept_key = _LANE_TO_DEPARTMENT.get(lane)
    if dept_key:
        try:
            from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS

            dept = SIX_LINE_DEPARTMENTS.get(dept_key) or {}
            subzones = dept.get("subzones") if isinstance(dept.get("subzones"), dict) else {}
            for sz in subzones.values():
                for pid in (sz.get("ids") or []) if isinstance(sz, dict) else []:
                    _push(pid)
        except Exception:  # noqa: BLE001
            logger.debug("surface audit: lane_employee_ids fallback lane=%s", lane)
    for pid in _LANE_OWNER_FALLBACK.get(lane, []):
        _push(pid)
    return out[: max(1, limit)]


def _rule_based_lane_analysis(lane: str, rows: List[Dict[str, Any]]) -> str:
    """bench LLM 不可用时的规则化分析（只陈述 HTTP / console 事实，不臆造）。"""
    if not rows:
        return "本产线本次无巡检页面。"
    ok = [r for r in rows if (r.get("status") or 0) < 400 and not r.get("error")]
    bad = [r for r in rows if r not in ok]
    ce_total = sum(len(r.get("console_errors") or []) for r in rows)
    parts = [f"巡检 {len(rows)} 页，正常 {len(ok)} 页"]
    if bad:
        names = "、".join(str(r.get("name") or r.get("url") or "?") for r in bad[:4])
        parts.append(f"异常 {len(bad)} 页（{names}）")
    if ce_total:
        parts.append(f"console 报错累计 {ce_total} 条，建议排查前端脚本")
    if not bad and not ce_total:
        parts.append("HTTP 与 console 均无异常")
    return "；".join(parts) + "。"


def _build_lane_analysis_user_content(
    lane: str, lane_label: str, rows: List[Dict[str, Any]]
) -> str:
    lines: List[str] = []
    for r in rows:
        ce = r.get("console_errors") or []
        ce_part = ("；console: " + " | ".join(str(x)[:160] for x in ce[:3])) if ce else ""
        err_part = f"；抓取错误: {r.get('error')}" if r.get("error") else ""
        lines.append(
            f"- {r.get('name')}（{r.get('viewport')}）｜URL {r.get('url')}｜HTTP {r.get('status') or '—'}"
            f"｜标题「{str(r.get('title') or '')[:80]}」{ce_part}{err_part}"
        )
    return (
        f"产线：{lane}（{lane_label}）。以下是本次 Playwright 巡检到的关键页面（截图已另存）：\n"
        + "\n".join(lines)
    )


_LANE_ANALYSIS_SYSTEM = """你是 MODstore「{lane}」产线在岗 AI 员工（{owners}）。
数字管家把本产线今天的页面巡检结果交给你，请只用本产线视角，基于给出的 HTTP 状态、
页面标题、console 报错等**确凿事实**写一段简体中文分析，**不得编造**未给出的内容。

严格按以下结构输出（不要加多余前后缀，控制在 6 行内）：
现状：<一句话概括本产线页面整体是否健康>
异常：<逐条列出 HTTP≥400 / 抓取失败 / console 报错；没有则写「无」>
改进建议：<1-3 条可落地动作，点名本产线相关文件或岗位；信息不足写「待确认」>"""


async def analyze_surface_lanes(report: Dict[str, Any], *, user_id: int = 0) -> Dict[str, Any]:
    """对 P-W / P-S / P-App 三条产线分别生成「对应员工」分析。

    返回 ``{lane: {markdown, owners, model, error, source}}``；
    bench LLM 不可用时 ``source='rule'`` 用规则化摘要兜底，保证每条产线都有分析文字。
    """
    enabled = (os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED", "1") or "").strip().lower()
    results = report.get("results") if isinstance(report.get("results"), list) else []
    out: Dict[str, Any] = {}
    if not results:
        return out

    lanes = ["P-W", "P-S", "P-App"]
    lane_labels = {"P-W": "网站 P-W", "P-S": "软件 P-S", "P-App": "移动 / App P-App"}
    for r in results:
        ll = str(r.get("lane_label") or "").strip()
        if ll and str(r.get("lane")) in lane_labels:
            lane_labels[str(r.get("lane"))] = ll

    bench_prov = bench_mdl = ""
    if enabled not in ("0", "false", "no", "off"):
        try:
            from modstore_server.services.llm import resolve_platform_bench_llm

            bench_prov, bench_mdl = resolve_platform_bench_llm()
        except Exception:  # noqa: BLE001
            logger.debug("surface audit: resolve_platform_bench_llm failed")

    for lane in lanes:
        rows = [r for r in results if str(r.get("lane")) == lane]
        if not rows:
            continue
        owners = lane_employee_ids(lane)
        rule_md = _rule_based_lane_analysis(lane, rows)
        if not bench_prov or not bench_mdl:
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": "",
                "error": "" if (enabled in ("0", "false", "no", "off")) else "bench LLM 未配置",
                "source": "rule",
            }
            continue
        system = _LANE_ANALYSIS_SYSTEM.format(lane=lane, owners="、".join(owners[:3]) or lane)
        user_content = _build_lane_analysis_user_content(lane, lane_labels.get(lane, lane), rows)
        try:
            from modstore_server.models import get_session_factory as _gsf
            from modstore_server.services.llm import chat_dispatch_via_session

            with _gsf()() as db:
                result = await chat_dispatch_via_session(
                    db,
                    int(user_id or 0),
                    bench_prov,
                    bench_mdl,
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=700,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("surface audit: lane analysis dispatch failed lane=%s err=%s", lane, exc)
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": str(exc)[:300],
                "source": "rule",
            }
            continue
        md = ""
        if isinstance(result, dict) and result.get("ok"):
            md = str(result.get("content") or "").strip()
            if not md:
                choices = result.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    msg0 = choices[0].get("message")
                    if isinstance(msg0, dict):
                        md = str(msg0.get("content") or "").strip()
        if md:
            out[lane] = {
                "markdown": md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": "",
                "source": "llm",
            }
        else:
            err = (
                str((result or {}).get("error") or "bench LLM 返回为空")
                if isinstance(result, dict)
                else "bench LLM 返回为空"
            )
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": err[:300],
                "source": "rule",
            }
    return out


async def _capture_surface_target_async(
    browser: Any,
    idx: int,
    target: "SurfaceTarget",
    *,
    base: str,
    save_root: Optional[Path],
    market_auth: Dict[str, str],
    timeout_ms: int,
) -> Dict[str, Any]:
    url = f"{target.base or base}{target.path}"
    save_path: Optional[Path] = None
    if save_root is not None:
        slug = f"{idx:03d}_{target.lane}_{_safe_slug_name(target.name)}"
        save_path = save_root / f"{slug}.png"
    ctx_kwargs: Dict[str, Any] = {"ignore_https_errors": True}
    if target.viewport == "mobile":
        ctx_kwargs.update(
            {
                "viewport": _MOBILE_VIEWPORT,
                "is_mobile": True,
                "has_touch": True,
                "user_agent": (
                    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
            }
        )
    else:
        ctx_kwargs["viewport"] = _DESKTOP_VIEWPORT
    context = await browser.new_context(**ctx_kwargs)
    try:
        if market_auth and _path_needs_market_auth(target.path):
            await _inject_market_auth(context, market_auth)
        if target.prepare == "admin_digest" and market_auth:
            await _prepare_admin_digest(context, market_auth)
        page = await context.new_page()
        row = await _capture_one(
            page,
            url=url,
            viewport=target.viewport,
            timeout_ms=timeout_ms,
            save_path=save_path,
            prepare=target.prepare,
        )
    finally:
        await context.close()
    row["lane"] = target.lane
    row["lane_label"] = target.lane_label
    row["name"] = target.name
    if "/market/admin/" in str(target.path or ""):
        row["admin"] = True
        row["digest_unlock_ok"] = bool(not row.get("error") and int(row.get("status") or 0) < 400)
    return row


async def run_surface_audit_async() -> Dict[str, Any]:
    enabled = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "results": []}

    try:
        timeout_ms = max(
            10_000, int(os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS", "45000"))
        )
    except ValueError:
        timeout_ms = 45_000

    base = _base_url()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_root = _save_dir(day)
    results: List[Dict[str, Any]] = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "未安装 playwright（pip install playwright && playwright install chromium）",
            "results": [],
        }

    market_auth = _login_surface_audit_sync()
    if market_auth:
        logger.info("surface audit: market login ok user=%s", market_auth.get("username"))
    else:
        logger.warning(
            "surface audit: market login skipped/failed; /market/* may capture login redirect"
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            import asyncio as _asyncio

            try:
                _conc = max(
                    1, min(12, int(os.environ.get("MODSTORE_SURFACE_AUDIT_CONCURRENCY", "4")))
                )
            except ValueError:
                _conc = 4
            _sem = _asyncio.Semaphore(_conc)
            _targets = list(default_surface_targets())

            async def _run_one(idx: int, target: SurfaceTarget) -> Dict[str, Any]:
                async with _sem:
                    return await _capture_surface_target_async(
                        browser,
                        idx,
                        target,
                        base=base,
                        save_root=save_root,
                        market_auth=market_auth,
                        timeout_ms=timeout_ms,
                    )

            results = list(await _asyncio.gather(*[_run_one(i, t) for i, t in enumerate(_targets)]))
        finally:
            await browser.close()

    ok = all((r.get("status") or 0) < 400 and not r.get("error") for r in results)
    baseline_delta = compute_surface_baseline_delta(day, results, save_root=save_root)

    if save_root is not None and results:
        try:
            (save_root / "manifest.json").write_text(
                json.dumps({"day": day, "results": results}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("surface audit: manifest write failed: %s", exc)

    raw_uid = (
        os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID")
        or os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    analysis_uid = int(raw_uid) if raw_uid.isdigit() else 0
    lane_analysis: Dict[str, Any] = {}
    try:
        lane_analysis = await analyze_surface_lanes({"results": results}, user_id=analysis_uid)
    except Exception:  # noqa: BLE001
        logger.exception("surface audit: lane analysis failed")
    for r in results:
        la = lane_analysis.get(str(r.get("lane")))
        if isinstance(la, dict):
            r["analysis"] = la.get("markdown") or ""
            r["analysis_owners"] = la.get("owners") or []

    return {
        "ok": ok,
        "skipped": False,
        "results": results,
        "day": day,
        "baseline_delta": baseline_delta,
        "lane_analysis": lane_analysis,
    }


def _lane_summary(results: List[Dict[str, Any]], lane: str) -> str:
    rows = [r for r in results if r.get("lane") == lane]
    if not rows:
        return "（无）"
    parts: List[str] = []
    for r in rows:
        st = r.get("status")
        flag = "✓" if (st or 0) < 400 and not r.get("error") else "✗"
        ce = len(r.get("console_errors") or [])
        parts.append(
            f"{flag} {r.get('name')} HTTP {st or '—'}"
            + (f" · console错误 {ce} 条" if ce else "")
            + (f" · {r.get('error')}" if r.get("error") else "")
        )
    return "\n".join(parts)


def _lane_analysis_md(report: Dict[str, Any], lane: str) -> str:
    la = report.get("lane_analysis") if isinstance(report.get("lane_analysis"), dict) else {}
    row = la.get(lane) if isinstance(la, dict) else None
    if not isinstance(row, dict):
        return ""
    md = str(row.get("markdown") or "").strip()
    if not md:
        return ""
    owners = row.get("owners") or []
    owner_line = f"（对应员工：{', '.join(str(o) for o in owners[:4])}）" if owners else ""
    return f"\n**分析**{owner_line}\n{md}"


def surface_audit_excerpt_markdown(report: Dict[str, Any]) -> str:
    if report.get("skipped"):
        return "（三端截图巡检已关闭）"
    if not report.get("ok") and report.get("error"):
        return f"（巡检失败：{report.get('error')}）"
    results = report.get("results") if isinstance(report.get("results"), list) else []
    if not results:
        return "（无巡检结果）"
    delta_md = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = "\n\n" + baseline_delta_excerpt_markdown(report["baseline_delta"])
    return (
        f"### P-W 网站\n{_lane_summary(results, 'P-W')}{_lane_analysis_md(report, 'P-W')}\n\n"
        f"### P-S 软件\n{_lane_summary(results, 'P-S')}{_lane_analysis_md(report, 'P-S')}\n\n"
        f"### P-App 移动 / App 面\n{_lane_summary(results, 'P-App')}{_lane_analysis_md(report, 'P-App')}"
        f"{delta_md}"
    )


def _render_analysis_block_html(report: Dict[str, Any], lane: str) -> str:
    la = report.get("lane_analysis") if isinstance(report.get("lane_analysis"), dict) else {}
    row = la.get(lane) if isinstance(la, dict) else None
    if not isinstance(row, dict):
        return ""
    md = str(row.get("markdown") or "").strip()
    if not md:
        return ""
    owners = row.get("owners") or []
    owner_html = (
        f'<span style="font-size:11px;color:#64748b">对应员工：{html.escape(", ".join(str(o) for o in owners[:4]))}</span>'
        if owners
        else ""
    )
    src = str(row.get("source") or "")
    src_badge = (
        '<span style="font-size:10px;color:#94a3b8">· 规则化兜底</span>' if src == "rule" else ""
    )
    body_lines = "".join(
        f'<div style="margin:2px 0">{html.escape(line.strip())}</div>'
        for line in md.splitlines()
        if line.strip()
    )
    return (
        '<div style="margin:4px 0 10px;padding:8px 10px;border-left:3px solid #6366f1;'
        'background:#eef2ff;border-radius:6px">'
        f'<div style="font-size:12px;font-weight:700;color:#4338ca;margin-bottom:3px">AI 分析 {owner_html} {src_badge}</div>'
        f'<div style="font-size:12px;color:#334155;line-height:1.55">{body_lines}</div>'
        "</div>"
    )


def _render_lane_html(
    lane: str, label: str, results: List[Dict[str, Any]], report: Optional[Dict[str, Any]] = None
) -> str:
    rows = [r for r in results if r.get("lane") == lane]
    if not rows:
        return ""
    items: List[str] = []
    for r in rows:
        st = r.get("status")
        bad = (st or 500) >= 400 or r.get("error")
        color = "#b91c1c" if bad else "#047857"
        ce = r.get("console_errors") or []
        ce_html = ""
        if ce:
            ce_html = (
                '<ul style="margin:4px 0 0;padding-left:18px;font-size:12px;color:#92400e">'
                + "".join(f"<li>{html.escape(str(x)[:200])}</li>" for x in ce[:3])
                + "</ul>"
            )
        saved = r.get("screenshot_saved") or ""
        save_note = (
            f'<div style="font-size:11px;color:#64748b;margin-top:2px">截图：{html.escape(saved)}</div>'
            if saved
            else ""
        )
        items.append(
            f'<li style="margin:8px 0;padding:8px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0">'
            f'<div style="font-weight:600;color:#1e293b">{html.escape(str(r.get("name") or ""))}'
            f' <span style="font-size:11px;color:{color}">HTTP {st or "—"} · {html.escape(str(r.get("viewport") or ""))}</span></div>'
            f'<div style="font-size:12px;color:#64748b;margin-top:2px">{html.escape(str(r.get("url") or ""))}</div>'
            f'<div style="font-size:12px;color:#475569;margin-top:2px">{html.escape(str(r.get("title") or ""))}</div>'
            + (
                f'<div style="font-size:12px;color:#b91c1c;margin-top:4px">{html.escape(str(r.get("error")))}</div>'
                if r.get("error")
                else ""
            )
            + ce_html
            + save_note
            + "</li>"
        )
    analysis_html = _render_analysis_block_html(report or {}, lane)
    return (
        f'<div style="margin:12px 0">'
        f'<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:6px">{html.escape(label)}</div>'
        f"{analysis_html}"
        f'<ul style="list-style:none;margin:0;padding:0">{"".join(items)}</ul>'
        f"</div>"
    )


def _lane_count_overview_html(results: List[Dict[str, Any]]) -> str:
    """三端实测页数总览（数据驱动：实时统计 results 各 lane 行数 + 正常/异常，绝不写死）。"""
    lanes = (("P-W", "网站", "#2563eb"), ("P-S", "软件", "#0d9488"), ("P-App", "移动", "#7c3aed"))
    chips: List[str] = []
    for lane, label, color in lanes:
        rows = [r for r in results if r.get("lane") == lane]
        total = len(rows)
        bad = sum(1 for r in rows if (r.get("status") or 0) >= 400 or r.get("error"))
        ok = total - bad
        sub = "未巡检" if total == 0 else (f"{ok} 正常" + (f" · {bad} 异常" if bad else ""))
        sub_color = "#dc2626" if bad else "#94a3b8"
        chips.append(
            '<td style="width:33.33%;padding:0 5px;vertical-align:top">'
            '<div style="border:1px solid #d6f0e4;border-radius:10px;background:#ffffff;padding:8px 10px;text-align:center">'
            f'<div style="font-size:11px;color:#64748b;font-weight:600">{label}</div>'
            f'<div style="font-size:20px;font-weight:800;color:{color};line-height:1.2;font-variant-numeric:tabular-nums">{total}'
            '<span style="font-size:11px;color:#94a3b8;font-weight:600"> 页</span></div>'
            f'<div style="font-size:10px;color:{sub_color};margin-top:2px">{sub}</div>'
            "</div></td>"
        )
    return (
        '<table role="presentation" style="width:100%;border-collapse:collapse;margin:0 0 12px"><tr>'
        + "".join(chips)
        + "</tr></table>"
    )


def build_surface_audit_html_sync() -> Tuple[str, Dict[str, Any]]:
    """同步入口：供 ``run_daily_digest_email`` 调用。返回 (html, report_dict)。"""
    enabled = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return "", {"ok": True, "skipped": True, "results": []}

    import asyncio

    try:
        report = asyncio.run(run_surface_audit_async())
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily surface audit failed")
        report = {"ok": False, "error": str(exc), "results": []}

    if report.get("skipped"):
        return "", report

    if report.get("error") and not report.get("results"):
        body = f'<p style="margin:0;font-size:13px;color:#b91c1c">三端页面巡检失败：{html.escape(str(report.get("error")))}</p>'
        return body, report

    results = report.get("results") if isinstance(report.get("results"), list) else []
    lanes_html = "".join(
        [
            _render_lane_html("P-W", "P-W · 获客网站", results, report),
            _render_lane_html("P-S", "P-S · MODstore 软件面", results, report),
            _render_lane_html("P-App", "P-App · 移动端 / App WebView", results, report),
        ]
    )
    ok_all = bool(report.get("ok"))
    badge = "全部通过" if ok_all else "存在异常页"
    badge_color = "#047857" if ok_all else "#b45309"
    delta_html = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = baseline_delta_excerpt_markdown(report["baseline_delta"])
        if delta_md.strip():
            delta_html = f'<p style="margin:10px 0 0;font-size:12px;color:#475569">{html.escape(delta_md).replace(chr(10), "<br/>")}</p>'
    overview_html = _lane_count_overview_html(results)
    html_out = (
        f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 16px">'
        f'<p style="margin:0 0 10px;font-size:12px;color:{badge_color};font-weight:700">{badge} · Playwright 全页截图 + console 采集</p>'
        f"{overview_html}"
        f"{lanes_html}"
        f"{delta_html}"
        f"</div>"
    )
    return html_out, report
