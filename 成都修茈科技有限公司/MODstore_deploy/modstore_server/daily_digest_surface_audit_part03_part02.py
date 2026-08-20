# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def build_digest_surface_targets() -> _facade().List[_facade().SurfaceTarget]:
    """日更默认：P-W 全量 + 商品详情 1–3；P-S/P-App 全量（P-App adb 开启时 Playwright 跳过）。"""
    base = _facade()._base_url()
    out: _facade().List[_facade().SurfaceTarget] = []
    out.extend(
        _facade()._build_pw_full_targets(base, catalog=_facade()._pw_catalog_items_for_daily(base))
    )
    if _facade()._ps_audit_enabled():
        ps_base = _facade()._ps_base_url()
        for name, path in _facade()._PS_DESKTOP_PAGES:
            out.append(
                _facade().SurfaceTarget("P-S", "软件 P-S", name, path, "desktop", base=ps_base)
            )
    for name, path in _facade()._PAPP_PUBLIC_PAGES:
        out.append(_facade().SurfaceTarget("P-App", "App P-App", name, path, "mobile"))
    for tab_name, tab_id in _facade()._AI_STORE_TABS:
        out.append(
            _facade().SurfaceTarget(
                "P-App",
                "App P-App",
                f"{tab_name}（移动）",
                "/market/ai-store",
                "mobile",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )
    return out


def build_surface_targets() -> _facade().List[_facade().SurfaceTarget]:
    """CI ``full``：P-W 全量 + 可选 catalog（仍受 CATALOG_MAX 限制）；P-S/P-App 全量。"""
    base = _facade()._base_url()
    catalog: _facade().List[_facade().Dict[str, _facade().Any]] = []
    if _facade()._catalog_fetch_enabled():
        catalog = _facade()._filter_catalog_ai_employee_items(
            _facade()._fetch_market_catalog_sync(base)
        )
    out: _facade().List[_facade().SurfaceTarget] = []
    out.extend(_facade()._build_pw_full_targets(base, catalog=catalog))
    if _facade()._ps_audit_enabled():
        ps_base = _facade()._ps_base_url()
        for name, path in _facade()._PS_DESKTOP_PAGES:
            out.append(
                _facade().SurfaceTarget("P-S", "软件 P-S", name, path, "desktop", base=ps_base)
            )
    for name, path in _facade()._PAPP_PUBLIC_PAGES:
        out.append(_facade().SurfaceTarget("P-App", "App P-App", name, path, "mobile"))
    for tab_name, tab_id in _facade()._AI_STORE_TABS:
        out.append(
            _facade().SurfaceTarget(
                "P-App",
                "App P-App",
                f"{tab_name}（移动）",
                "/market/ai-store",
                "mobile",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )
    return out


def default_surface_targets() -> _facade().List[_facade().SurfaceTarget]:
    """日更 digest：默认 ``daily``（三端全量，P-W 商品详情 1–3）；``sample``/``full`` 见模块说明。"""
    if _facade()._is_full_surface_audit():
        return _facade().build_surface_targets()
    if _facade()._is_sample_surface_audit():
        return _facade()._pick_sample_targets(_facade().build_surface_targets())
    return _facade().build_digest_surface_targets()


def _repo_root() -> _facade().Path:
    try:
        from modstore_server.daily_digest import _repo_root as root_fn

        return _facade().Path(root_fn())
    except _facade().RECOVERABLE_ERRORS:
        return _facade().Path(_facade().os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()


def _png_fingerprint(path: _facade().Path) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    return _facade().hashlib.sha256(data).hexdigest()[:16]


def compute_surface_baseline_delta(
    day: str,
    results: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    save_root: _facade().Optional[_facade().Path] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Compare today's PNG fingerprints vs previous calendar day (file hash)."""
    root = save_root if save_root is not None else _facade()._save_dir(day)
    if root is None:
        return {"ok": True, "skipped": True, "reason": "no save dir", "rows": []}
    prev_day = (
        _facade().datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_facade().timezone.utc)
        - _facade().timedelta(days=1)
    ).strftime("%Y-%m-%d")
    prev_root = root.parent / prev_day
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    changed = 0
    for r in results:
        saved = str(r.get("screenshot_saved") or "").strip()
        if not saved:
            continue
        cur = _facade().Path(saved)
        prev = prev_root / cur.name
        cur_fp = _facade()._png_fingerprint(cur)
        prev_fp = _facade()._png_fingerprint(prev) if prev.is_file() else ""
        delta = "new" if not prev_fp else "same" if cur_fp == prev_fp else "changed"
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


def baseline_delta_excerpt_markdown(delta: _facade().Dict[str, _facade().Any]) -> str:
    if delta.get("skipped"):
        return "（相对昨日 Δ：未保存截图目录，跳过）"
    rows = delta.get("rows") if isinstance(delta.get("rows"), list) else []
    if not rows:
        return "（相对昨日 Δ：无截图可对比）"
    parts: _facade().List[str] = []
    for row in rows:
        flag = row.get("delta") or "?"
        sym = {"same": "＝", "changed": "≠", "new": "＋"}.get(str(flag), "?")
        parts.append(f"{sym} {row.get('name')} ({flag})")
    summary = f"变更 {delta.get('changed_count', 0)} 页"
    return f"**相对昨日 Δ** · {summary}\n" + "\n".join(parts)


def _save_dir(day: str) -> _facade().Optional[_facade().Path]:
    raw = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR")
        or "playwright-report/digest-surfaces"
    ).strip()
    if not raw or raw.lower() in ("0", "false", "no", "off", "none"):
        return None
    out = _facade()._repo_root() / raw / day
    out.mkdir(parents=True, exist_ok=True)
    return out
