# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def _base_url() -> str:
    raw = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com"
    ).strip()
    return raw.rstrip("/")


def _ps_base_url() -> str:
    """P-S 软件（本地企业版客户端）基址。

    与 FHD ``surface_audit_service`` 同口径：默认 ``http://127.0.0.1:5001``，
    可用 ``MODSTORE_SURFACE_AUDIT_PS_BASE_URL`` 覆盖（生产可指向可达的企业版宿主）。
    """
    raw = (
        _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PS_BASE_URL")
        or _facade().os.environ.get("SURFACE_AUDIT_BASE_URL")
        or "http://127.0.0.1:5001"
    ).strip()
    return raw.rstrip("/")


def _ps_audit_enabled() -> bool:
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _safe_slug_name(name: str) -> str:
    return _facade().re.sub('[\\\\/:*?"<>|]+', "-", str(name or "")).strip()[:96] or "page"


def _fetch_market_catalog_sync(
    base: str, *, max_items: _facade().Optional[int] = None
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """拉取 AI 市场公开目录（用于 /market/catalog/:id 截图）；不全量分页，够筛 1–3 即停。"""
    cap = _facade()._catalog_screenshot_max()
    if cap <= 0:
        return []
    need = max_items if max_items is not None else max(cap * 6, 12)
    items: _facade().List[_facade().Dict[str, _facade().Any]] = []
    internal = _facade()._internal_api_base()
    bases: _facade().List[str] = []
    for candidate in (internal, base.rstrip("/")):
        if candidate and candidate not in bases:
            bases.append(candidate)
    for api_base in bases:
        url = f"{api_base}/api/market/catalog"
        seen = 0
        batch_items: _facade().List[_facade().Dict[str, _facade().Any]] = []
        while url and seen < 20:
            seen += 1
            req = _facade().urllib.request.Request(
                url, headers={"User-Agent": "MODstore-surface-audit/1.0"}
            )
            try:
                with _facade().urllib.request.urlopen(req, timeout=60) as resp:
                    payload = _facade().json.loads(resp.read().decode("utf-8", errors="replace"))
            except (
                _facade().urllib.error.URLError,
                TimeoutError,
                _facade().json.JSONDecodeError,
            ) as exc:
                _facade().logger.warning(
                    "surface audit: catalog fetch failed base=%s: %s", api_base, exc
                )
                batch_items = []
                break
            if isinstance(payload, dict):
                batch = payload.get("items")
                if isinstance(batch, list):
                    batch_items.extend((x for x in batch if isinstance(x, dict)))
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
    return (
        (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_MODE") or "daily").strip().lower()
    )


def _is_full_surface_audit() -> bool:
    return _facade()._surface_audit_mode() in ("full", "all", "complete")


def _is_sample_surface_audit() -> bool:
    return _facade()._surface_audit_mode() in ("sample", "one", "minimal")


def _is_daily_surface_audit() -> bool:
    return not _facade()._is_full_surface_audit() and (not _facade()._is_sample_surface_audit())


def _max_targets_per_lane() -> int:
    raw = (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _catalog_screenshot_max() -> int:
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_CATALOG_MAX") or "3").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


def _catalog_fetch_enabled() -> bool:
    if _facade()._catalog_screenshot_max() <= 0:
        return False
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG") or "").strip().lower()
    if _facade()._is_daily_surface_audit():
        if not raw:
            return True
        return raw in ("0", "false", "no", "off")
    if not _facade()._is_full_surface_audit():
        return False
    raw = raw or "1"
    return raw in ("0", "false", "no", "off")


def _stable_sample_catalog_items(
    items: _facade().List[_facade().Dict[str, _facade().Any]], cap: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """按 UTC 日稳定抽样，避免每次 digest 总截同一批商品。"""
    if cap <= 0 or not items:
        return []
    if len(items) <= cap:
        return list(items)
    day = _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")
    ranked = sorted(
        items,
        key=lambda item: (
            _facade()
            .hashlib.sha256(f"{day}:{item.get('id') or item.get('pkg_id') or ''}".encode())
            .hexdigest()
        ),
    )
    return ranked[:cap]


def _is_ai_employee_material(item: _facade().Dict[str, _facade().Any]) -> bool:
    cat = str(item.get("material_category") or item.get("category") or "").strip().lower()
    if cat == "ai_employee":
        return True
    artifact = str(item.get("artifact_type") or item.get("artifact") or "").strip().lower()
    return artifact in ("ai_employee", "workflow_employee")


def _filter_catalog_ai_employee_items(
    items: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """catalog 详情截图：先筛 AI 员工类商品，再稳定抽 1–3 张（默认 3）。"""
    if not items:
        return []
    ai_only = [x for x in items if isinstance(x, dict) and _facade()._is_ai_employee_material(x)]
    pool = ai_only if ai_only else items
    return _facade()._stable_sample_catalog_items(pool, _facade()._catalog_screenshot_max())


def _is_ai_employee_store_target(t: _facade().SurfaceTarget) -> bool:
    prep = (t.prepare or "").strip().lower()
    return t.path == "/market/ai-store" and "ai_employee" in prep


def _is_ps_ai_employee_target(t: _facade().SurfaceTarget) -> bool:
    """P-S 企业版：智能生态 = AI 员工/生态主界面（对齐 surface_audit_pages preview）。"""
    if t.lane != "P-S":
        return False
    path = (t.path or "").strip().lower()
    if path in ("/ai-ecosystem",):
        return True
    return "智能生态" in (t.name or "")


def _is_papp_ai_ecosystem_target(t: _facade().SurfaceTarget) -> bool:
    return t.lane == "P-App" and (t.path or "").strip().lower() == "/ai-ecosystem"


def _pick_lane_sample_target(
    targets: _facade().List[_facade().SurfaceTarget], lane: str
) -> _facade().Optional[_facade().SurfaceTarget]:
    """三产线 sample：各 lane 优先 AI 员工专属页，再退 catalog（仅 P-W）/列表首项。"""
    lane_targets = [t for t in targets if t.lane == lane]
    if not lane_targets:
        return None
    predicates = {
        "P-W": (_facade()._is_ai_employee_store_target,),
        "P-S": (_facade()._is_ps_ai_employee_target,),
        "P-App": (
            _facade()._is_ai_employee_store_target,
            _facade()._is_papp_ai_ecosystem_target,
        ),
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


def _pick_sample_targets(
    full: _facade().List[_facade().SurfaceTarget],
) -> _facade().List[_facade().SurfaceTarget]:
    """日更 sample：P-W / P-S / P-App 各 1 张 AI 员工代表截图。"""
    per_lane = _facade()._max_targets_per_lane()
    out: _facade().List[_facade().SurfaceTarget] = []
    for lane in ("P-W", "P-S", "P-App"):
        picked = _facade()._pick_lane_sample_target(full, lane)
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
    targets: _facade().List[_facade().SurfaceTarget], *, per_lane: int
) -> _facade().List[_facade().SurfaceTarget]:
    if per_lane <= 0:
        return list(targets)
    counts: _facade().Dict[str, int] = {}
    out: _facade().List[_facade().SurfaceTarget] = []
    for t in targets:
        n = counts.get(t.lane, 0)
        if n >= per_lane:
            continue
        out.append(t)
        counts[t.lane] = n + 1
    return out


def _append_pw_catalog_targets(
    out: _facade().List[_facade().SurfaceTarget],
    catalog: _facade().List[_facade().Dict[str, _facade().Any]],
) -> None:
    for item in catalog:
        cid = item.get("id")
        if cid is None:
            continue
        label = str(item.get("name") or item.get("pkg_id") or cid).strip()
        out.append(
            _facade().SurfaceTarget(
                "P-W",
                "网站 P-W",
                f"AI员工商品-{label}",
                f"/market/catalog/{cid}",
                "desktop",
            )
        )


def _pw_catalog_items_for_daily(
    base: str,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """日更 P-W：公开商品详情抽样 1–3（其余 P-W 页全量）。"""
    if _facade()._catalog_screenshot_max() <= 0:
        return []
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return []
    return _facade()._filter_catalog_ai_employee_items(_facade()._fetch_market_catalog_sync(base))


def _build_pw_full_targets(
    base: str,
    *,
    catalog: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().List[_facade().SurfaceTarget]:
    """P-W 全量页面清单；``catalog`` 由调用方注入（日更为 1–3 张商品详情）。"""
    items = catalog if catalog is not None else []
    out: _facade().List[_facade().SurfaceTarget] = []
    for name, path in _facade()._STATIC_PW_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PW_MARKET_ENTRY_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PS_PUBLIC_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for tab_name, tab_id in _facade()._AI_STORE_TABS:
        out.append(
            _facade().SurfaceTarget(
                "P-W",
                "网站 P-W",
                tab_name,
                "/market/ai-store",
                "desktop",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )
    for name, path, prepare in _facade()._PW_AI_MARKET_EXTRA_PAGES:
        out.append(
            _facade().SurfaceTarget(
                "P-W", "网站 P-W", name, path, "desktop", prepare=prepare or None
            )
        )
    _facade()._append_pw_catalog_targets(out, items)
    for name, path, mode in _facade()._PW_WB_MODE_PAGES:
        out.append(
            _facade().SurfaceTarget(
                "P-W", "网站 P-W", name, path, "desktop", prepare=f"wb_mode:{mode}"
            )
        )
    for name, path in _facade()._PW_SIDEBAR_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PW_WORKBENCH_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PW_AI_TEST_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PW_ACCOUNT_PAGES:
        out.append(_facade().SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))
    for name, path in _facade()._PW_MARKET_ADMIN_PAGES:
        out.append(
            _facade().SurfaceTarget(
                "P-W", "网站 P-W", name, path, "desktop", prepare="admin_digest"
            )
        )
    return out
