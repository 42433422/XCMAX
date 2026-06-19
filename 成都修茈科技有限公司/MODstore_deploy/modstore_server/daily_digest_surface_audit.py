"""每日摘要 · 三端页面截图巡检（P-W 网站 / P-S 软件 / P-App 移动 App 面）。

Playwright 抓取关键 URL 全页截图，记录 HTTP 状态与 console error，供邮件段落与 Vibe 预备引用。

环境变量：
- ``MODSTORE_DAILY_SURFACE_AUDIT_ENABLED``（默认 ``1``）：设为 ``0`` 关闭本段落。
- ``MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL``：站点根（默认 ``https://xiu-ci.com``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS``（默认 ``45000``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_MODE``（默认 ``daily``）：``daily`` 日更 — P-W/P-S/P-App 全量，P-W 公开商品详情仅 1–3 张；``sample`` 三产线各 1 张；``full`` 同 ``daily``（CI 别名）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE``（默认 ``1``）：仅 ``sample`` 模式下每产线最多几张。
- ``MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR``：可选，保存 PNG 目录（默认 ``playwright-report/digest-surfaces`` 相对仓库根）。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED``（默认 ``1``）：是否对每条产线截图调用 bench LLM 生成「对应员工」的现状 / 异常 / 改进建议分析；未配置 bench LLM 时回退到基于 HTTP / console 的规则化摘要。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID``：分析调用 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_SURFACE_AUDIT_USER`` / ``MODSTORE_SURFACE_AUDIT_PASSWORD``：AI 市场 SPA 截图前登录（默认 ``admin`` / ``admin123``）。
- ``MODSTORE_SURFACE_AUDIT_API_URL``：登录 API 根（默认 ``MODSTORE_INTERNAL_API_BASE`` 或站点 ``base_url``）。
- ``MODSTORE_SURFACE_AUDIT_ANDROID``（默认 ``1``）：P-App 走本地 adb + 模拟器（``FHD/scripts/ci/run_android_surface_audit.mjs``），不再用 Playwright 移动 Web 截 xiu-ci.com。
- ``MODSTORE_SURFACE_AUDIT_CATALOG_MAX``（默认 ``3``）：P-W 市场公开商品详情 ``/market/catalog/:id`` 抽样 1–3 张（0=不截 catalog）。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _internal_api_base() -> str:
    """MODstore 登录 / catalog / digest-identity API 根（Mac 本地默认 :8788，非生产 :9990）。"""
    from modstore_server.surface_audit_deps import resolve_internal_api_base

    return resolve_internal_api_base()


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
    ("智能生态（移动）", "/ai-ecosystem"),
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


def _fetch_market_catalog_sync(base: str, *, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    """拉取 AI 市场公开目录（用于 /market/catalog/:id 截图）；不全量分页，够筛 1–3 即停。"""
    cap = _catalog_screenshot_max()
    if cap <= 0:
        return []
    need = max_items if max_items is not None else max(cap * 6, 12)
    items: List[Dict[str, Any]] = []
    internal = _internal_api_base()
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
            if len(batch_items) >= need:
                batch_items = batch_items[:need]
                url = ""
        if batch_items:
            items = batch_items
            break
    return items


def _surface_audit_mode() -> str:
    return (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_MODE") or "daily").strip().lower()


def _is_full_surface_audit() -> bool:
    return _surface_audit_mode() in ("full", "all", "complete")


def _is_sample_surface_audit() -> bool:
    return _surface_audit_mode() in ("sample", "one", "minimal")


def _is_daily_surface_audit() -> bool:
    return not _is_full_surface_audit() and not _is_sample_surface_audit()


def _max_targets_per_lane() -> int:
    raw = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _catalog_screenshot_max() -> int:
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_CATALOG_MAX") or "3").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


def _catalog_fetch_enabled() -> bool:
    if _catalog_screenshot_max() <= 0:
        return False
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG") or "").strip().lower()
    if _is_daily_surface_audit():
        if not raw:
            return True
        return raw in ("0", "false", "no", "off")
    if not _is_full_surface_audit():
        return False
    raw = raw or "1"
    return raw in ("0", "false", "no", "off")


def _stable_sample_catalog_items(items: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """按 UTC 日稳定抽样，避免每次 digest 总截同一批商品。"""
    if cap <= 0 or not items:
        return []
    if len(items) <= cap:
        return list(items)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ranked = sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{day}:{item.get('id') or item.get('pkg_id') or ''}".encode()
        ).hexdigest(),
    )
    return ranked[:cap]


def _is_ai_employee_material(item: Dict[str, Any]) -> bool:
    cat = str(item.get("material_category") or item.get("category") or "").strip().lower()
    if cat == "ai_employee":
        return True
    artifact = str(item.get("artifact_type") or item.get("artifact") or "").strip().lower()
    return artifact in ("ai_employee", "workflow_employee")


def _filter_catalog_ai_employee_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """catalog 详情截图：先筛 AI 员工类商品，再稳定抽 1–3 张（默认 3）。"""
    if not items:
        return []
    ai_only = [x for x in items if isinstance(x, dict) and _is_ai_employee_material(x)]
    pool = ai_only if ai_only else items
    return _stable_sample_catalog_items(pool, _catalog_screenshot_max())


def _is_ai_employee_store_target(t: SurfaceTarget) -> bool:
    prep = (t.prepare or "").strip().lower()
    return t.path == "/market/ai-store" and "ai_employee" in prep


def _is_ps_ai_employee_target(t: SurfaceTarget) -> bool:
    """P-S 企业版：智能生态 = AI 员工/生态主界面（对齐 surface_audit_pages preview）。"""
    if t.lane != "P-S":
        return False
    path = (t.path or "").strip().lower()
    if path in ("/ai-ecosystem",):
        return True
    return "智能生态" in (t.name or "")


def _is_papp_ai_ecosystem_target(t: SurfaceTarget) -> bool:
    return t.lane == "P-App" and (t.path or "").strip().lower() == "/ai-ecosystem"


def _pick_lane_sample_target(targets: List[SurfaceTarget], lane: str) -> Optional[SurfaceTarget]:
    """三产线 sample：各 lane 优先 AI 员工专属页，再退 catalog（仅 P-W）/列表首项。"""
    lane_targets = [t for t in targets if t.lane == lane]
    if not lane_targets:
        return None

    predicates = {
        "P-W": (_is_ai_employee_store_target,),
        "P-S": (_is_ps_ai_employee_target,),
        # 移动：先 AI 市场 Tab，再智能生态（与 P-W/P-S 同一「AI 员工面」语义）
        "P-App": (_is_ai_employee_store_target, _is_papp_ai_ecosystem_target),
    }.get(lane, ())

    for pred in predicates:
        for t in lane_targets:
            if pred(t):
                return t

    if lane == "P-W":
        catalog = [t for t in lane_targets if "/market/catalog/" in t.path]
        if catalog:
            return catalog[0]

    return lane_targets[0]


def _pick_sample_targets(full: List[SurfaceTarget]) -> List[SurfaceTarget]:
    """日更 sample：P-W / P-S / P-App 各 1 张 AI 员工代表截图。"""
    per_lane = _max_targets_per_lane()
    out: List[SurfaceTarget] = []
    for lane in ("P-W", "P-S", "P-App"):
        picked = _pick_lane_sample_target(full, lane)
        if picked is None:
            continue
        out.append(picked)
        if per_lane <= 1:
            continue
        extras = 0
        for t in full:
            if t.lane != lane or t is picked:
                continue
            if extras >= per_lane - 1:
                break
            out.append(t)
            extras += 1
    return out


def _limit_targets_per_lane(
    targets: List[SurfaceTarget], *, per_lane: int
) -> List[SurfaceTarget]:
    if per_lane <= 0:
        return list(targets)
    counts: Dict[str, int] = {}
    out: List[SurfaceTarget] = []
    for t in targets:
        n = counts.get(t.lane, 0)
        if n >= per_lane:
            continue
        out.append(t)
        counts[t.lane] = n + 1
    return out


def _append_pw_catalog_targets(
    out: List[SurfaceTarget], catalog: List[Dict[str, Any]]
) -> None:
    for item in catalog:
        cid = item.get("id")
        if cid is None:
            continue
        label = str(item.get("name") or item.get("pkg_id") or cid).strip()
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                f"AI员工商品-{label}",
                f"/market/catalog/{cid}",
                "desktop",
            )
        )


def _pw_catalog_items_for_daily(base: str) -> List[Dict[str, Any]]:
    """日更 P-W：公开商品详情抽样 1–3（其余 P-W 页全量）。"""
    if _catalog_screenshot_max() <= 0:
        return []
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return []
    return _filter_catalog_ai_employee_items(_fetch_market_catalog_sync(base))


def _build_pw_full_targets(
    base: str, *, catalog: Optional[List[Dict[str, Any]]] = None
) -> List[SurfaceTarget]:
    """P-W 全量页面清单；``catalog`` 由调用方注入（日更为 1–3 张商品详情）。"""
    items = catalog if catalog is not None else []
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

    _append_pw_catalog_targets(out, items)

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

    return out


def build_digest_surface_targets() -> List[SurfaceTarget]:
    """日更默认：P-W 全量 + 商品详情 1–3；P-S/P-App 全量（P-App adb 开启时 Playwright 跳过）。"""
    base = _base_url()
    out: List[SurfaceTarget] = []
    out.extend(_build_pw_full_targets(base, catalog=_pw_catalog_items_for_daily(base)))

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


def build_surface_targets() -> List[SurfaceTarget]:
    """CI ``full``：P-W 全量 + 可选 catalog（仍受 CATALOG_MAX 限制）；P-S/P-App 全量。"""
    base = _base_url()
    catalog: List[Dict[str, Any]] = []
    if _catalog_fetch_enabled():
        catalog = _filter_catalog_ai_employee_items(_fetch_market_catalog_sync(base))
    out: List[SurfaceTarget] = []
    out.extend(_build_pw_full_targets(base, catalog=catalog))

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
    """日更 digest：默认 ``daily``（三端全量，P-W 商品详情 1–3）；``sample``/``full`` 见模块说明。"""
    if _is_full_surface_audit():
        return build_surface_targets()
    if _is_sample_surface_audit():
        return _pick_sample_targets(build_surface_targets())
    return build_digest_surface_targets()


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


def _surface_demo_account_defaults() -> Tuple[str, str]:
    fallback = ("xcagi-enterprise-demo", "Demo@2026")
    candidates: List[Path] = []
    raw_cfg = (os.environ.get("MODSTORE_RUNTIME_CONFIG_ROOT") or "").strip()
    if raw_cfg:
        candidates.append(Path(raw_cfg).expanduser().resolve() / "surface_audit_demo_account.json")
    try:
        candidates.append(_repo_root() / "FHD" / "config" / "surface_audit_demo_account.json")
    except Exception:
        pass
    for path in candidates:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            user = str(cfg.get("username") or fallback[0]).strip()
            password = str(cfg.get("password") or fallback[1])
            if user and password:
                return user, password
        except Exception:
            continue
    return fallback


def _surface_audit_login_api_base(account_kind: str) -> str:
    """按巡检对象选择登录 API 根。

    P-W/MODstore 市场页使用 MODstore 内部 API（默认 :8788）；P-S 企业客户端页面
    使用 FHD API（默认 SURFACE_AUDIT_API_URL/:5102）。两者 session/token 存储不共用。
    """
    if account_kind == "enterprise":
        raw = (
            os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_API_URL")
            or os.environ.get("MODSTORE_SURFACE_AUDIT_PS_API_URL")
            or os.environ.get("SURFACE_AUDIT_API_URL")
            or "http://127.0.0.1:5102"
        )
        return str(raw).strip().rstrip("/")
    raw = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL") or _internal_api_base()
    )
    return str(raw).strip().rstrip("/")


def _login_surface_audit_sync(
    *,
    account_kind: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    label: str = "market",
) -> Dict[str, Any]:
    """Playwright 截图前登录对应系统，并返回可注入的 token/cookie/session。"""
    account_kind = (account_kind or os.environ.get("MODSTORE_SURFACE_AUDIT_ACCOUNT_KIND") or "admin").strip()
    api_base = _surface_audit_login_api_base(account_kind)
    if account_kind == "enterprise":
        demo_user, demo_password = _surface_demo_account_defaults()
        user = (
            user
            or os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_USER")
            or os.environ.get("SURFACE_AUDIT_ENTERPRISE_USER")
            or os.environ.get("SURFACE_AUDIT_USER")
            or demo_user
        )
        password = (
            password
            or os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_PASSWORD")
            or os.environ.get("SURFACE_AUDIT_ENTERPRISE_PASSWORD")
            or os.environ.get("SURFACE_AUDIT_PASSWORD")
            or demo_password
        )
    else:
        user = user or os.environ.get("MODSTORE_SURFACE_AUDIT_USER") or "admin"
        password = password or os.environ.get("MODSTORE_SURFACE_AUDIT_PASSWORD") or "admin123"
    user = str(user).strip()
    password = str(password).strip()

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
        logger.warning("surface audit: %s login failed base=%s err=%s", label, api_base, exc)
        return {}

    ok = bool(web.get("ok") or web.get("success"))
    data = web.get("data") if isinstance(web.get("data"), dict) else {}
    access = str(
        web.get("access_token")
        or web.get("token")
        or web.get("market_access_token")
        or data.get("access_token")
        or data.get("token")
        or data.get("market_access_token")
        or ""
    ).strip()
    refresh = str(
        web.get("refresh_token")
        or web.get("market_refresh_token")
        or data.get("refresh_token")
        or data.get("market_refresh_token")
        or ""
    ).strip()
    session_id = str(
        web.get("session_id")
        or data.get("session_id")
        or cookies.get("session_id")
        or cookies.get("admin_session_id")
        or ""
    ).strip()
    csrf = str(cookies.get("csrf_token") or "").strip()

    if account_kind == "enterprise" and ok and session_id and not access:
        try:
            handoff, _ = _req(f"{api_base}/api/market/session-handoff")
            handoff_data = handoff.get("data") if isinstance(handoff.get("data"), dict) else {}
            access = str(
                handoff_data.get("market_access_token") or handoff_data.get("token") or ""
            ).strip()
            refresh = str(
                handoff_data.get("market_refresh_token") or handoff_data.get("refresh_token") or refresh
            ).strip()
        except Exception as exc:
            logger.warning("surface audit: %s session-handoff failed base=%s err=%s", label, api_base, exc)

    has_required_state = bool(access) or (account_kind == "enterprise" and bool(session_id))
    if not ok or not has_required_state:
        logger.warning(
            "surface audit: %s login rejected base=%s msg=%s",
            label,
            api_base,
            web.get("message") or web.get("error") or "no access_token",
        )
        return {}
    return {
        "access_token": access,
        "refresh_token": refresh,
        "session_id": session_id,
        "csrf_token": csrf,
        "username": user,
        "account_kind": account_kind,
        "api_base": api_base,
        "cookies": cookies,
        "raw": web,
    }


def _fetch_admin_digest_code_sync(auth: Dict[str, str]) -> str:
    """从 MODstore API 拉取管理端 6 位校验码（对齐 FHD digest-identity 自签发）。"""
    api_base = (
        (os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL") or _internal_api_base()).strip().rstrip("/")
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
                (os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL") or _internal_api_base())
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


def _cookie_url_for_auth(target_url: str, auth: Dict[str, Any]) -> str:
    for candidate in (target_url, str(auth.get("api_base") or "")):
        try:
            parsed = urllib.parse.urlsplit(candidate)
        except Exception:
            continue
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
    return "http://127.0.0.1/"


async def _inject_market_auth(context: Any, auth: Dict[str, Any], target_url: str = "") -> None:
    cookies = auth.get("cookies") if isinstance(auth.get("cookies"), dict) else {}
    session_id = str(auth.get("session_id") or cookies.get("session_id") or "").strip()
    csrf = str(auth.get("csrf_token") or cookies.get("csrf_token") or "").strip()
    cookie_rows: List[Dict[str, str]] = []
    cookie_url = _cookie_url_for_auth(target_url, auth)
    for name, value in {**cookies, "session_id": session_id, "csrf_token": csrf}.items():
        v = str(value or "").strip()
        if name and v:
            cookie_rows.append({"name": str(name), "value": v, "url": cookie_url})
    if cookie_rows:
        try:
            await context.add_cookies(cookie_rows)
        except Exception as exc:
            logger.warning("surface audit: inject auth cookies failed url=%s err=%s", cookie_url, exc)

    access = str(auth.get("access_token") or "").strip()
    if not access and not session_id:
        return
    refresh = str(auth.get("refresh_token") or "").strip()
    account_kind = str(auth.get("account_kind") or "").strip()
    username = str(auth.get("username") or "").strip()
    market_user = {
        "username": username,
        "account_kind": account_kind,
        "market_is_enterprise": account_kind == "enterprise",
        "is_admin": account_kind == "admin",
    }
    script = (
        "(function(){try{"
        + (f"localStorage.setItem('modstore_token', {json.dumps(access)});" if access else "")
        + (f"localStorage.setItem('xcagi_market_access_token', {json.dumps(access)});" if access else "")
        + (
            f"localStorage.setItem('modstore_refresh_token', {json.dumps(refresh)});"
            f"localStorage.setItem('xcagi_market_refresh_token', {json.dumps(refresh)});"
            if refresh
            else ""
        )
        + (f"localStorage.setItem('xcagi_surface_audit_session_id', {json.dumps(session_id)});" if session_id else "")
        + f"localStorage.setItem('xcagi_market_user_json', {json.dumps(json.dumps(market_user, ensure_ascii=False))});"
        + "}catch(e){}})();"
    )
    await context.add_init_script(script)


async def _goto_with_retry(page: Any, url: str, *, timeout_ms: int) -> Any:
    """远程站点易抖动：domcontentloaded 失败后降级 commit 再试（对齐 run_surface_audit.mjs）。"""
    try:
        return await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as first_exc:
        try:
            resp = await page.goto(url, wait_until="commit", timeout=timeout_ms)
        except Exception:
            raise first_exc
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        return resp


_TRANSIENT_NAV_ERROR_MARKERS: Tuple[str, ...] = (
    "Timeout",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_NETWORK_CHANGED",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_QUIC_PROTOCOL_ERROR",
    "net::ERR_FAILED",
)


def _surface_capture_retry_count() -> int:
    raw = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_RETRIES") or "2").strip()
    try:
        return max(0, min(4, int(raw)))
    except ValueError:
        return 2


def _is_retryable_surface_row(row: Dict[str, Any]) -> bool:
    err = str(row.get("error") or "")
    if err and any(marker in err for marker in _TRANSIENT_NAV_ERROR_MARKERS):
        return True
    try:
        status = int(row.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    return status in (408, 425, 429) or status >= 500


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
        resp = await _goto_with_retry(page, url, timeout_ms=timeout_ms)
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
        try:
            png = await page.screenshot(full_page=False, type="png")
            if save_path is not None:
                save_path.write_bytes(png)
        except Exception:
            pass
        if not save_path or not save_path.is_file():
            return {
                "url": url,
                "status": status,
                "title": title,
                "console_errors": console_errors[:8],
                "error": err,
                "screenshot_saved": "",
                "viewport": viewport,
                "prepare": prepare or "",
            }
    if not save_path or not save_path.is_file():
        if err:
            return {
                "url": url,
                "status": status,
                "title": title,
                "console_errors": console_errors[:8],
                "error": err,
                "screenshot_saved": "",
                "viewport": viewport,
                "prepare": prepare or "",
            }
        raise RuntimeError(f"surface audit screenshot missing url={url}")
    return {
        "url": url,
        "status": status,
        "title": title,
        "console_errors": console_errors[:8],
        "error": None,
        "screenshot_saved": str(save_path),
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


def _surface_analysis_timeout_sec() -> float:
    raw = (os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_TIMEOUT_SEC") or "90").strip()
    try:
        return max(10.0, min(600.0, float(raw)))
    except ValueError:
        return 90.0


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
                "error": "" if enabled in ("0", "false", "no", "off") else "bench LLM 未配置",
                "source": "rule",
            }
            if enabled not in ("0", "false", "no", "off"):
                logger.warning("surface audit: lane analysis fallback lane=%s err=bench LLM 未配置", lane)
            continue
        system = _LANE_ANALYSIS_SYSTEM.format(lane=lane, owners="、".join(owners[:3]) or lane)
        user_content = _build_lane_analysis_user_content(lane, lane_labels.get(lane, lane), rows)
        try:
            import asyncio as _asyncio

            from modstore_server.models import get_session_factory as _gsf
            from modstore_server.services.llm import chat_dispatch_via_session

            with _gsf()() as db:
                result = await _asyncio.wait_for(
                    chat_dispatch_via_session(
                        db,
                        int(user_id or 0),
                        bench_prov,
                        bench_mdl,
                        [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_content},
                        ],
                        max_tokens=700,
                    ),
                    timeout=_surface_analysis_timeout_sec(),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("surface audit: lane analysis dispatch failed lane=%s err=%s", lane, exc)
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": str(exc),
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
            logger.warning("surface audit: lane analysis empty lane=%s err=%s", lane, err)
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": err,
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
        if market_auth and (target.lane == "P-S" or _path_needs_market_auth(target.path)):
            await _inject_market_auth(context, market_auth, url)
        if target.prepare == "admin_digest" and market_auth:
            await _prepare_admin_digest(context, market_auth)
        row: Dict[str, Any] = {}
        attempts = 1 + _surface_capture_retry_count()
        for attempt in range(attempts):
            page = await context.new_page()
            try:
                row = await _capture_one(
                    page,
                    url=url,
                    viewport=target.viewport,
                    timeout_ms=timeout_ms,
                    save_path=save_path,
                    prepare=target.prepare,
                )
            except Exception as exc:  # noqa: BLE001
                row = {
                    "url": url,
                    "status": None,
                    "title": "",
                    "console_errors": [],
                    "error": str(exc),
                    "screenshot_saved": str(save_path) if save_path and save_path.is_file() else "",
                    "viewport": target.viewport,
                    "prepare": target.prepare or "",
                }
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
            if attempt >= attempts - 1 or not _is_retryable_surface_row(row):
                break
            logger.warning(
                "surface audit: retry target=%s attempt=%s/%s err=%s status=%s",
                target.name,
                attempt + 2,
                attempts,
                str(row.get("error") or "")[:240],
                row.get("status"),
            )
            try:
                import asyncio as _asyncio

                await _asyncio.sleep(min(8, 2 * (attempt + 1)))
            except Exception:
                pass
    finally:
        await context.close()
    row["lane"] = target.lane
    row["lane_label"] = target.lane_label
    row["name"] = target.name
    if target.lane == "P-S":
        title = str(row.get("title") or "")
        final_url = str(row.get("url") or url)
        console_blob = "\n".join(str(x) for x in (row.get("console_errors") or [])[:10])
        auth_bad = (
            "登录" in title
            or "/login" in final_url
            or "401" in console_blob
            or "unauthorized" in console_blob.lower()
        )
        row["auth_account_kind"] = str((market_auth or {}).get("account_kind") or "")
        row["auth_state_ok"] = not auth_bad
        if auth_bad and not row.get("error"):
            row["error"] = "P-S enterprise auth state invalid: landed on login/401"
    if "/market/admin/" in str(target.path or ""):
        row["admin"] = True
        row["digest_unlock_ok"] = bool(not row.get("error") and int(row.get("status") or 0) < 400)
    return row


async def run_surface_audit_async() -> Dict[str, Any]:
    enabled = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "results": []}

    try:
        from modstore_server.surface_audit_deps import ensure_surface_audit_deps

        deps = ensure_surface_audit_deps()
        if not deps.get("ok"):
            failures = deps.get("failures") or deps
            raise RuntimeError(f"surface audit deps not ready: {failures}")
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"surface audit deps bootstrap failed: {exc}") from exc

    try:
        timeout_ms = max(
            10_000, int(os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS", "90000"))
        )
    except ValueError:
        timeout_ms = 90_000

    base = _base_url()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_root = _save_dir(day)
    results: List[Dict[str, Any]] = []

    from modstore_server.daily_digest_surface_audit_android import (
        _android_enabled,
        run_android_surface_audit_sync,
    )

    android_rows: List[Dict[str, Any]] = []
    android_meta: Dict[str, Any] = {}
    use_android = _android_enabled()
    if use_android:
        try:
            android_rows, android_meta = run_android_surface_audit_sync(
                save_root=save_root,
                sample=_is_sample_surface_audit(),
            )
            if android_meta.get("ok"):
                logger.info(
                    "surface audit: P-App android adb ok pages=%s devices=%s",
                    android_meta.get("page_count"),
                    android_meta.get("device_count"),
                )
            elif android_meta.get("error"):
                logger.warning("surface audit: P-App android adb: %s", android_meta.get("error"))
        except Exception:
            logger.exception("surface audit: P-App android audit failed")

    _targets_all = list(default_surface_targets())
    logger.info(
        "surface audit: mode=%s targets=%s lanes=%s catalog_max=%s android=%s",
        _surface_audit_mode(),
        len(_targets_all),
        {lane: sum(1 for t in _targets_all if t.lane == lane) for lane in ("P-W", "P-S", "P-App")},
        _catalog_screenshot_max(),
        _android_enabled(),
    )
    _targets = [t for t in _targets_all if not (use_android and t.lane == "P-App")]
    if use_android and len(_targets_all) != len(_targets):
        logger.info(
            "surface audit: P-App %s 页改走 adb 模拟器（非 Playwright 移动 Web）",
            len(_targets_all) - len(_targets),
        )

    normalized: List[Dict[str, Any]] = []
    if _targets:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            if android_rows:
                results = android_rows
            else:
                return {
                    "ok": False,
                    "error": "未安装 playwright（pip install playwright && playwright install chromium）",
                    "results": [],
                }
        else:
            market_auth = _login_surface_audit_sync(label="P-W")
            if market_auth:
                logger.info("surface audit: market login ok user=%s", market_auth.get("username"))
            elif any(_path_needs_market_auth(t.path) for t in _targets):
                raise RuntimeError(
                    "surface audit: market login required for /market/* pages but login failed "
                    "(check MODSTORE_SURFACE_AUDIT_USER/PASSWORD)"
                )
            else:
                logger.info("surface audit: no market-auth pages in target set; login skipped")
            ps_auth: Dict[str, str] = {}
            if any(t.lane == "P-S" for t in _targets):
                ps_auth = _login_surface_audit_sync(account_kind="enterprise", label="P-S")
                if ps_auth:
                    logger.info("surface audit: P-S enterprise login ok user=%s", ps_auth.get("username"))
                else:
                    raise RuntimeError(
                        "surface audit: P-S enterprise login required but login failed "
                        "(check SURFACE_AUDIT_API_URL and MODSTORE_SURFACE_AUDIT_ENTERPRISE_USER/PASSWORD)"
                    )

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    import asyncio as _asyncio

                    try:
                        _conc = max(
                            1,
                            min(12, int(os.environ.get("MODSTORE_SURFACE_AUDIT_CONCURRENCY", "4"))),
                        )
                    except ValueError:
                        _conc = 4
                    _sem = _asyncio.Semaphore(_conc)

                    async def _run_one(idx: int, target: SurfaceTarget) -> Dict[str, Any]:
                        async with _sem:
                            auth = ps_auth if target.lane == "P-S" else market_auth
                            return await _capture_surface_target_async(
                                browser,
                                idx,
                                target,
                                base=base,
                                save_root=save_root,
                                market_auth=auth,
                                timeout_ms=timeout_ms,
                            )

                    pw_results = list(
                        await _asyncio.gather(
                            *[_run_one(i, t) for i, t in enumerate(_targets)],
                            return_exceptions=True,
                        )
                    )
                    for i, item in enumerate(pw_results):
                        if isinstance(item, Exception):
                            t = _targets[i]
                            normalized.append(
                                {
                                    "url": f"{t.base or base}{t.path}",
                                    "status": None,
                                    "title": "",
                                    "console_errors": [],
                                    "error": str(item),
                                    "screenshot_saved": "",
                                    "lane": t.lane,
                                    "lane_label": t.lane_label,
                                    "name": t.name,
                                    "viewport": t.viewport,
                                    "prepare": t.prepare or "",
                                }
                            )
                        else:
                            normalized.append(item)
                finally:
                    await browser.close()

    results = android_rows + normalized

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
    lane_analysis = await analyze_surface_lanes({"results": results}, user_id=analysis_uid)
    for r in results:
        la = lane_analysis.get(str(r.get("lane")))
        if isinstance(la, dict):
            r["analysis"] = la.get("markdown") or ""
            r["analysis_owners"] = la.get("owners") or []

    if not ok:
        bad = [
            r
            for r in results
            if r.get("error") or int(r.get("status") or 0) >= 400
        ]
        sample = bad[0] if bad else {}
        raise RuntimeError(
            f"surface audit failed: {len(bad)} page(s) with errors; "
            f"first={sample.get('name') or sample.get('url')}: {sample.get('error') or sample.get('status')}"
        )

    return {
        "ok": True,
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
    cap = _email_lane_row_cap()
    visible = rows[:cap]
    items: List[str] = []
    for r in visible:
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
    more = len(rows) - len(visible)
    more_html = (
        f'<li style="margin:8px 0;font-size:12px;color:#64748b">… 另有 {more} 页未在邮件中展开（见 manifest / PPT 附件）</li>'
        if more > 0
        else ""
    )
    analysis_html = _render_analysis_block_html(report or {}, lane)
    return (
        f'<div style="margin:12px 0">'
        f'<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:6px">{html.escape(label)}</div>'
        f"{analysis_html}"
        f'<ul style="list-style:none;margin:0;padding:0">{"".join(items)}{more_html}</ul>'
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
        warn = sum(
            1
            for r in rows
            if not ((r.get("status") or 0) >= 400 or r.get("error")) and (r.get("console_errors") or [])
        )
        ok = total - bad - warn
        if total == 0:
            sub = "未巡检"
            sub_color = "#dc2626"
        elif bad:
            sub = f"{ok} 正常 · {bad} 异常" + (f" · {warn} 告警" if warn else "")
            sub_color = "#dc2626"
        elif warn:
            sub = f"{ok} 正常 · {warn} console 告警"
            sub_color = "#d97706"
        else:
            sub = f"{ok} 正常"
            sub_color = "#94a3b8"
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


def _surface_audit_badge(results: List[Dict[str, Any]]) -> Tuple[str, str, str]:
    """返回 (badge 文案, 颜色, 副标题)。"""
    if not results:
        return "未巡检", "#b45309", "三端截图未执行或结果为空"
    bad = sum(1 for r in results if (r.get("status") or 0) >= 400 or r.get("error"))
    warn = sum(
        1
        for r in results
        if not ((r.get("status") or 0) >= 400 or r.get("error")) and (r.get("console_errors") or [])
    )
    ps_missing = not any(r.get("lane") == "P-S" for r in results)
    android_n = sum(1 for r in results if r.get("android_capture"))
    papp_n = sum(1 for r in results if r.get("lane") == "P-App")
    if android_n and papp_n:
        capture_note = f"P-App adb {android_n} 屏"
    elif papp_n:
        capture_note = f"P-App Playwright {papp_n} 页"
    else:
        capture_note = "P-App 未截"
    subtitle = f"P-W/P-S Playwright + {capture_note} · console 采集"
    if bad:
        return f"{bad} 页异常", "#b91c1c", subtitle
    if ps_missing:
        return "P-S 未巡检", "#b45309", subtitle
    if warn:
        return f"{warn} 页 console 告警", "#b45309", subtitle
    return "全部通过", "#047857", subtitle


def _email_lane_row_cap() -> int:
    raw = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_EMAIL_MAX_ROWS") or "8").strip()
    try:
        return max(3, int(raw))
    except ValueError:
        return 8


def build_surface_audit_html_sync() -> Tuple[str, Dict[str, Any]]:
    """同步入口：供 ``run_daily_digest_email`` 调用。返回 (html, report_dict)。

    任一页截图/分析失败即抛错，不生成「存在异常页」兜底 HTML。
    """
    enabled = (os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return "", {"ok": True, "skipped": True, "results": []}

    import asyncio

    report = asyncio.run(run_surface_audit_async())

    if report.get("skipped"):
        return "", report

    results = report.get("results") if isinstance(report.get("results"), list) else []
    lanes_html = "".join(
        [
            _render_lane_html("P-W", "P-W · 获客网站", results, report),
            _render_lane_html("P-S", "P-S · MODstore 软件面", results, report),
            _render_lane_html("P-App", "P-App · 移动端 / adb 原生屏", results, report),
        ]
    )
    ok_all = True
    badge, badge_color, badge_sub = _surface_audit_badge(results)
    delta_html = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = baseline_delta_excerpt_markdown(report["baseline_delta"])
        if delta_md.strip():
            delta_html = f'<p style="margin:10px 0 0;font-size:12px;color:#475569">{html.escape(delta_md).replace(chr(10), "<br/>")}</p>'
    overview_html = _lane_count_overview_html(results)
    html_out = (
        f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 16px">'
        f'<p style="margin:0 0 10px;font-size:12px;color:{badge_color};font-weight:700">{badge} · {html.escape(badge_sub)}</p>'
        f"{overview_html}"
        f"{lanes_html}"
        f"{delta_html}"
        f"</div>"
    )
    return html_out, report
