# mypy: disable-error-code="assignment, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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

            bench_prov, bench_mdl = resolve_platform_bench_llm()
        except RECOVERABLE_ERRORS:
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
                    "surface audit: lane analysis fallback lane=%s err=bench LLM 未配置",
                    lane,
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
        except RECOVERABLE_ERRORS as exc:
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
            except RECOVERABLE_ERRORS as exc:
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
                except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS:
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
