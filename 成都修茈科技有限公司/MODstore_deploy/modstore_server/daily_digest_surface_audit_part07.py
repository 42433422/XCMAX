# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


async def analyze_surface_lanes(
    report: _facade().Dict[str, _facade().Any], *, user_id: int = 0
) -> _facade().Dict[str, _facade().Any]:
    """对 P-W / P-S / P-App 三条产线分别生成「对应员工」分析。

    返回 ``{lane: {markdown, owners, model, error, source}}``；
    bench LLM 不可用时 ``source='rule'`` 用规则化摘要兜底，保证每条产线都有分析文字。
    """
    enabled = (
        (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED", "1") or "")
        .strip()
        .lower()
    )
    results = report.get("results") if isinstance(report.get("results"), list) else []
    out: _facade().Dict[str, _facade().Any] = {}
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

            (bench_prov, bench_mdl) = resolve_platform_bench_llm()
        except Exception:
            _facade().logger.debug("surface audit: resolve_platform_bench_llm failed")
    for lane in lanes:
        rows = [r for r in results if str(r.get("lane")) == lane]
        if not rows:
            continue
        owners = _facade().lane_employee_ids(lane)
        rule_md = _facade()._rule_based_lane_analysis(lane, rows)
        if not bench_prov or not bench_mdl:
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": "",
                "error": "" if enabled in ("0", "false", "no", "off") else "bench LLM 未配置",
                "source": "rule",
            }
            if enabled not in ("0", "false", "no", "off"):
                _facade().logger.warning(
                    "surface audit: lane analysis fallback lane=%s err=bench LLM 未配置", lane
                )
            continue
        system = _facade()._LANE_ANALYSIS_SYSTEM.format(
            lane=lane, owners="、".join(owners[:3]) or lane
        )
        user_content = _facade()._build_lane_analysis_user_content(
            lane, lane_labels.get(lane, lane), rows
        )
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
                    timeout=_facade()._surface_analysis_timeout_sec(),
                )
        except Exception as exc:
            _facade().logger.warning(
                "surface audit: lane analysis dispatch failed lane=%s err=%s", lane, exc
            )
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
            _facade().logger.warning("surface audit: lane analysis empty lane=%s err=%s", lane, err)
            out[lane] = {
                "markdown": rule_md,
                "owners": owners,
                "model": f"{bench_prov}/{bench_mdl}",
                "error": err,
                "source": "rule",
            }
    return out


async def _capture_surface_target_async(
    browser: _facade().Any,
    idx: int,
    target: _facade().SurfaceTarget,
    *,
    base: str,
    save_root: _facade().Optional[_facade().Path],
    market_auth: _facade().Dict[str, str],
    timeout_ms: int,
) -> _facade().Dict[str, _facade().Any]:
    url = f"{target.base or base}{target.path}"
    save_path: _facade().Optional[_facade().Path] = None
    if save_root is not None:
        slug = f"{idx:03d}_{target.lane}_{_facade()._safe_slug_name(target.name)}"
        save_path = save_root / f"{slug}.png"
    ctx_kwargs: _facade().Dict[str, _facade().Any] = {"ignore_https_errors": True}
    if target.viewport == "mobile":
        ctx_kwargs.update(
            {
                "viewport": _facade()._MOBILE_VIEWPORT,
                "is_mobile": True,
                "has_touch": True,
                "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            }
        )
    else:
        ctx_kwargs["viewport"] = _facade()._DESKTOP_VIEWPORT
    context = await browser.new_context(**ctx_kwargs)
    try:
        if market_auth and (target.lane == "P-S" or _facade()._path_needs_market_auth(target.path)):
            await _facade()._inject_market_auth(context, market_auth, url)
        if target.prepare == "admin_digest" and market_auth:
            await _facade()._prepare_admin_digest(context, market_auth)
        row: _facade().Dict[str, _facade().Any] = {}
        attempts = 1 + _facade()._surface_capture_retry_count()
        for attempt in range(attempts):
            page = await context.new_page()
            try:
                row = await _facade()._capture_one(
                    page,
                    url=url,
                    viewport=target.viewport,
                    timeout_ms=timeout_ms,
                    save_path=save_path,
                    prepare=target.prepare,
                )
            except Exception as exc:
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
            if attempt >= attempts - 1 or not _facade()._is_retryable_surface_row(row):
                break
            _facade().logger.warning(
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
        console_blob = "\n".join((str(x) for x in (row.get("console_errors") or [])[:10]))
        auth_bad = (
            "登录" in title
            or "/login" in final_url
            or "401" in console_blob
            or ("unauthorized" in console_blob.lower())
        )
        row["auth_account_kind"] = str((market_auth or {}).get("account_kind") or "")
        row["auth_state_ok"] = not auth_bad
        if auth_bad and (not row.get("error")):
            row["error"] = "P-S enterprise auth state invalid: landed on login/401"
    if "/market/admin/" in str(target.path or ""):
        row["admin"] = True
        row["digest_unlock_ok"] = bool(not row.get("error") and int(row.get("status") or 0) < 400)
    return row


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
    except Exception as exc:
        raise RuntimeError(f"surface audit deps bootstrap failed: {exc}") from exc
    try:
        timeout_ms = max(
            10000, int(_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS", "90000"))
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
            (android_rows, android_meta) = run_android_surface_audit_sync(
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
        except Exception:
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
                    "surface audit: market login ok user=%s", market_auth.get("username")
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
        f"""<span style="font-size:11px;color:#64748b">对应员工：{_facade().html.escape(', '.join((str(o) for o in owners[:4])))}</span>"""
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
            f"""<li style="margin:8px 0;padding:8px 10px;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0"><div style="font-weight:600;color:#1e293b">{_facade().html.escape(str(r.get('name') or ''))} <span style="font-size:11px;color:{color}">HTTP {st or '—'} · {_facade().html.escape(str(r.get('viewport') or ''))}</span></div><div style="font-size:12px;color:#64748b;margin-top:2px">{_facade().html.escape(str(r.get('url') or ''))}</div><div style="font-size:12px;color:#475569;margin-top:2px">{_facade().html.escape(str(r.get('title') or ''))}</div>"""
            + (
                f"""<div style="font-size:12px;color:#b91c1c;margin-top:4px">{_facade().html.escape(str(r.get('error')))}</div>"""
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
    return f"""<div style="margin:12px 0"><div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:6px">{_facade().html.escape(label)}</div>{analysis_html}<ul style="list-style:none;margin:0;padding:0">{''.join(items)}{more_html}</ul></div>"""


def _lane_count_overview_html(results: _facade().List[_facade().Dict[str, _facade().Any]]) -> str:
    """三端实测页数总览（数据驱动：实时统计 results 各 lane 行数 + 正常/异常，绝不写死）。"""
    lanes = (("P-W", "网站", "#2563eb"), ("P-S", "软件", "#0d9488"), ("P-App", "移动", "#7c3aed"))
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


def _surface_audit_badge(
    results: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Tuple[str, str, str]:
    """返回 (badge 文案, 颜色, 副标题)。"""
    if not results:
        return ("未巡检", "#b45309", "三端截图未执行或结果为空")
    bad = sum((1 for r in results if (r.get("status") or 0) >= 400 or r.get("error")))
    warn = sum(
        (
            1
            for r in results
            if not ((r.get("status") or 0) >= 400 or r.get("error"))
            and (r.get("console_errors") or [])
        )
    )
    ps_missing = not any((r.get("lane") == "P-S" for r in results))
    android_n = sum((1 for r in results if r.get("android_capture")))
    papp_n = sum((1 for r in results if r.get("lane") == "P-App"))
    if android_n and papp_n:
        capture_note = f"P-App adb {android_n} 屏"
    elif papp_n:
        capture_note = f"P-App Playwright {papp_n} 页"
    else:
        capture_note = "P-App 未截"
    subtitle = f"P-W/P-S Playwright + {capture_note} · console 采集"
    if bad:
        return (f"{bad} 页异常", "#b91c1c", subtitle)
    if ps_missing:
        return ("P-S 未巡检", "#b45309", subtitle)
    if warn:
        return (f"{warn} 页 console 告警", "#b45309", subtitle)
    return ("全部通过", "#047857", subtitle)


def _email_lane_row_cap() -> int:
    raw = (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_EMAIL_MAX_ROWS") or "8").strip()
    try:
        return max(3, int(raw))
    except ValueError:
        return 8


def build_surface_audit_html_sync() -> _facade().Tuple[str, _facade().Dict[str, _facade().Any]]:
    """同步入口：供 ``run_daily_digest_email`` 调用。返回 (html, report_dict)。

    任一页截图/分析失败即抛错，不生成「存在异常页」兜底 HTML。
    """
    enabled = (
        (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_ENABLED", "1") or "")
        .strip()
        .lower()
    )
    if enabled in ("0", "false", "no", "off"):
        return ("", {"ok": True, "skipped": True, "results": []})
    import asyncio

    report = asyncio.run(_facade().run_surface_audit_async())
    if report.get("skipped"):
        return ("", report)
    results = report.get("results") if isinstance(report.get("results"), list) else []
    lanes_html = "".join(
        [
            _facade()._render_lane_html("P-W", "P-W · 获客网站", results, report),
            _facade()._render_lane_html("P-S", "P-S · MODstore 软件面", results, report),
            _facade()._render_lane_html("P-App", "P-App · 移动端 / adb 原生屏", results, report),
        ]
    )
    (badge, badge_color, badge_sub) = _facade()._surface_audit_badge(results)
    delta_html = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = _facade().baseline_delta_excerpt_markdown(report["baseline_delta"])
        if delta_md.strip():
            delta_html = f"""<p style="margin:10px 0 0;font-size:12px;color:#475569">{_facade().html.escape(delta_md).replace(chr(10), '<br/>')}</p>"""
    overview_html = _facade()._lane_count_overview_html(results)
    html_out = f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 16px"><p style="margin:0 0 10px;font-size:12px;color:{badge_color};font-weight:700">{badge} · {_facade().html.escape(badge_sub)}</p>{overview_html}{lanes_html}{delta_html}</div>'
    return (html_out, report)
