# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


async def run_surface_audit_async() -> _facade().Dict[str, _facade().Any]:
    enabled = (
        (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "")
        .strip()
        .lower()
    )
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
    except RECOVERABLE_ERRORS as exc:
        raise RuntimeError(f"surface audit deps bootstrap failed: {exc}") from exc
    try:
        timeout_ms = max(
            10000,
            int(_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS", "90000")),
        )
    except ValueError:
        timeout_ms = 90000
    base = _facade()._base_url()
    day = _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")
    save_root = _facade()._save_dir(day)
    results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    from modstore_server.daily_digest_surface_audit_android import (
        _android_enabled,
        run_android_surface_audit_sync,
    )

    android_rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    android_meta: _facade().Dict[str, _facade().Any] = {}
    use_android = _android_enabled()
    if use_android:
        try:
            android_rows, android_meta = run_android_surface_audit_sync(
                save_root=save_root, sample=_facade()._is_sample_surface_audit()
            )
            if android_meta.get("ok"):
                _facade().logger.info(
                    "surface audit: P-App android adb ok pages=%s devices=%s",
                    android_meta.get("page_count"),
                    android_meta.get("device_count"),
                )
            elif android_meta.get("error"):
                _facade().logger.warning(
                    "surface audit: P-App android adb: %s", android_meta.get("error")
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("surface audit: P-App android audit failed")
    _targets_all = list(_facade().default_surface_targets())
    _facade().logger.info(
        "surface audit: mode=%s targets=%s lanes=%s catalog_max=%s android=%s",
        _facade()._surface_audit_mode(),
        len(_targets_all),
        {
            lane: sum((1 for t in _targets_all if t.lane == lane))
            for lane in ("P-W", "P-S", "P-App")
        },
        _facade()._catalog_screenshot_max(),
        _android_enabled(),
    )
    _targets = [t for t in _targets_all if not (use_android and t.lane == "P-App")]
    if use_android and len(_targets_all) != len(_targets):
        _facade().logger.info(
            "surface audit: P-App %s 页改走 adb 模拟器（非 Playwright 移动 Web）",
            len(_targets_all) - len(_targets),
        )
    normalized: _facade().List[_facade().Dict[str, _facade().Any]] = []
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
            market_auth = _facade()._login_surface_audit_sync(label="P-W")
            if market_auth:
                _facade().logger.info(
                    "surface audit: market login ok user=%s",
                    market_auth.get("username"),
                )
            elif any((_facade()._path_needs_market_auth(t.path) for t in _targets)):
                raise RuntimeError(
                    "surface audit: market login required for /market/* pages but login failed (check MODSTORE_SURFACE_AUDIT_USER/PASSWORD)"
                )
            else:
                _facade().logger.info(
                    "surface audit: no market-auth pages in target set; login skipped"
                )
            ps_auth: _facade().Dict[str, str] = {}
            if any((t.lane == "P-S" for t in _targets)):
                ps_auth = _facade()._login_surface_audit_sync(
                    account_kind="enterprise", label="P-S"
                )
                if ps_auth:
                    _facade().logger.info("surface audit: P-S enterprise login ok")
                else:
                    raise RuntimeError(
                        "surface audit: P-S enterprise login required but login failed (check SURFACE_AUDIT_API_URL and MODSTORE_SURFACE_AUDIT_ENTERPRISE_USER/PASSWORD)"
                    )
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    import asyncio as _asyncio

                    try:
                        _conc = max(
                            1,
                            min(
                                12,
                                int(
                                    _facade().os.environ.get(
                                        "MODSTORE_SURFACE_AUDIT_CONCURRENCY", "4"
                                    )
                                ),
                            ),
                        )
                    except ValueError:
                        _conc = 4
                    _sem = _asyncio.Semaphore(_conc)

                    async def _run_one(
                        idx: int, target: _facade().SurfaceTarget
                    ) -> _facade().Dict[str, _facade().Any]:
                        async with _sem:
                            auth = ps_auth if target.lane == "P-S" else market_auth
                            return await _facade()._capture_surface_target_async(
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
                            *[_run_one(i, t) for (i, t) in enumerate(_targets)],
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
    ok = all(((r.get("status") or 0) < 400 and (not r.get("error")) for r in results))
    baseline_delta = _facade().compute_surface_baseline_delta(day, results, save_root=save_root)
    if save_root is not None and results:
        try:
            (save_root / "manifest.json").write_text(
                _facade().json.dumps(
                    {"day": day, "results": results}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            _facade().logger.warning("surface audit: manifest write failed: %s", exc)
    raw_uid = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID")
        or _facade().os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    analysis_uid = int(raw_uid) if raw_uid.isdigit() else 0
    lane_analysis: _facade().Dict[str, _facade().Any] = {}
    lane_analysis = await _facade().analyze_surface_lanes(
        {"results": results}, user_id=analysis_uid
    )
    for r in results:
        la = lane_analysis.get(str(r.get("lane")))
        if isinstance(la, dict):
            r["analysis"] = la.get("markdown") or ""
            r["analysis_owners"] = la.get("owners") or []
    if not ok:
        bad = [r for r in results if r.get("error") or int(r.get("status") or 0) >= 400]
        sample = bad[0] if bad else {}
        raise RuntimeError(
            f"surface audit failed: {len(bad)} page(s) with errors; first={sample.get('name') or sample.get('url')}: {sample.get('error') or sample.get('status')}"
        )
    return {
        "ok": True,
        "skipped": False,
        "results": results,
        "day": day,
        "baseline_delta": baseline_delta,
        "lane_analysis": lane_analysis,
    }


def _lane_summary(results: _facade().List[_facade().Dict[str, _facade().Any]], lane: str) -> str:
    rows = [r for r in results if r.get("lane") == lane]
    if not rows:
        return "（无）"
    parts: _facade().List[str] = []
    for r in rows:
        st = r.get("status")
        flag = "✓" if (st or 0) < 400 and (not r.get("error")) else "✗"
        ce = len(r.get("console_errors") or [])
        parts.append(
            f"{flag} {r.get('name')} HTTP {st or '—'}"
            + (f" · console错误 {ce} 条" if ce else "")
            + (f" · {r.get('error')}" if r.get("error") else "")
        )
    return "\n".join(parts)


def _lane_analysis_md(report: _facade().Dict[str, _facade().Any], lane: str) -> str:
    la = report.get("lane_analysis") if isinstance(report.get("lane_analysis"), dict) else {}
    row = la.get(lane) if isinstance(la, dict) else None
    if not isinstance(row, dict):
        return ""
    md = str(row.get("markdown") or "").strip()
    if not md:
        return ""
    owners = row.get("owners") or []
    owner_line = f"（对应员工：{', '.join((str(o) for o in owners[:4]))}）" if owners else ""
    return f"\n**分析**{owner_line}\n{md}"


def surface_audit_excerpt_markdown(report: _facade().Dict[str, _facade().Any]) -> str:
    if report.get("skipped"):
        return "（三端截图巡检已关闭）"
    if not report.get("ok") and report.get("error"):
        return f"（巡检失败：{report.get('error')}）"
    results = report.get("results") if isinstance(report.get("results"), list) else []
    if not results:
        return "（无巡检结果）"
    delta_md = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = "\n\n" + _facade().baseline_delta_excerpt_markdown(report["baseline_delta"])
    return f"### P-W 网站\n{_facade()._lane_summary(results, 'P-W')}{_facade()._lane_analysis_md(report, 'P-W')}\n\n### P-S 软件\n{_facade()._lane_summary(results, 'P-S')}{_facade()._lane_analysis_md(report, 'P-S')}\n\n### P-App 移动 / App 面\n{_facade()._lane_summary(results, 'P-App')}{_facade()._lane_analysis_md(report, 'P-App')}{delta_md}"


def _render_analysis_block_html(report: _facade().Dict[str, _facade().Any], lane: str) -> str:
    la = report.get("lane_analysis") if isinstance(report.get("lane_analysis"), dict) else {}
    row = la.get(lane) if isinstance(la, dict) else None
    if not isinstance(row, dict):
        return ""
    md = str(row.get("markdown") or "").strip()
    if not md:
        return ""
    owners = row.get("owners") or []
    owner_html = (
        f"""<span style="font-size:11px;color:#64748b">对应员工：{_facade().html.escape(", ".join((str(o) for o in owners[:4])))}</span>"""
        if owners
        else ""
    )
    src = str(row.get("source") or "")
    src_badge = (
        '<span style="font-size:10px;color:#94a3b8">· 规则化兜底</span>' if src == "rule" else ""
    )
    body_lines = "".join(
        (
            f'<div style="margin:2px 0">{_facade().html.escape(line.strip())}</div>'
            for line in md.splitlines()
            if line.strip()
        )
    )
    return f'<div style="margin:4px 0 10px;padding:8px 10px;border-left:3px solid #6366f1;background:#eef2ff;border-radius:6px"><div style="font-size:12px;font-weight:700;color:#4338ca;margin-bottom:3px">AI 分析 {owner_html} {src_badge}</div><div style="font-size:12px;color:#334155;line-height:1.55">{body_lines}</div></div>'


def _render_lane_html(
    lane: str,
    label: str,
    results: _facade().List[_facade().Dict[str, _facade().Any]],
    report: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> str:
    rows = [r for r in results if r.get("lane") == lane]
    if not rows:
        return ""
    cap = _facade()._email_lane_row_cap()
    visible = rows[:cap]
    items: _facade().List[str] = []
    for r in visible:
        st = r.get("status")
        bad = (st or 500) >= 400 or r.get("error")
        color = "#b91c1c" if bad else "#047857"
        ce = r.get("console_errors") or []
        ce_html = ""
        if ce:
            ce_html = (
                '<ul style="margin:4px 0 0;padding-left:18px;font-size:12px;color:#92400e">'
                + "".join((f"<li>{_facade().html.escape(str(x)[:200])}</li>" for x in ce[:3]))
                + "</ul>"
            )
        saved = r.get("screenshot_saved") or ""
        save_note = (
            f'<div style="font-size:11px;color:#64748b;margin-top:2px">截图：{_facade().html.escape(saved)}</div>'
            if saved
            else ""
        )
        items.append(
            f"""<li style="margin:8px 0;padding:8px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0"><div style="font-weight:600;color:#1e293b">{_facade().html.escape(str(r.get("name") or ""))} <span style="font-size:11px;color:{color}">HTTP {st or "—"} · {_facade().html.escape(str(r.get("viewport") or ""))}</span></div><div style="font-size:12px;color:#64748b;margin-top:2px">{_facade().html.escape(str(r.get("url") or ""))}</div><div style="font-size:12px;color:#475569;margin-top:2px">{_facade().html.escape(str(r.get("title") or ""))}</div>"""
            + (
                f"""<div style="font-size:12px;color:#b91c1c;margin-top:4px">{_facade().html.escape(str(r.get("error")))}</div>"""
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
    analysis_html = _facade()._render_analysis_block_html(report or {}, lane)
    return f"""<div style="margin:12px 0"><div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:6px">{_facade().html.escape(label)}</div>{analysis_html}<ul style="list-style:none;margin:0;padding:0">{"".join(items)}{more_html}</ul></div>"""


def _lane_count_overview_html(
    results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> str:
    """三端实测页数总览（数据驱动：实时统计 results 各 lane 行数 + 正常/异常，绝不写死）。"""
    lanes = (
        ("P-W", "网站", "#2563eb"),
        ("P-S", "软件", "#0d9488"),
        ("P-App", "移动", "#7c3aed"),
    )
    chips: _facade().List[str] = []
    for lane, label, color in lanes:
        rows = [r for r in results if r.get("lane") == lane]
        total = len(rows)
        bad = sum((1 for r in rows if (r.get("status") or 0) >= 400 or r.get("error")))
        warn = sum(
            (
                1
                for r in rows
                if not ((r.get("status") or 0) >= 400 or r.get("error"))
                and (r.get("console_errors") or [])
            )
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
            f'<td style="width:33.33%;padding:0 5px;vertical-align:top"><div style="border:1px solid #d6f0e4;border-radius:10px;background:#ffffff;padding:8px 10px;text-align:center"><div style="font-size:11px;color:#64748b;font-weight:600">{label}</div><div style="font-size:20px;font-weight:800;color:{color};line-height:1.2;font-variant-numeric:tabular-nums">{total}<span style="font-size:11px;color:#94a3b8;font-weight:600"> 页</span></div><div style="font-size:10px;color:{sub_color};margin-top:2px">{sub}</div></div></td>'
        )
    return (
        '<table role="presentation" style="width:100%;border-collapse:collapse;margin:0 0 12px"><tr>'
        + "".join(chips)
        + "</tr></table>"
    )
