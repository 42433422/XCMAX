# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def _surface_audit_badge(
    results: _facade().List[_facade().Dict[str, _facade().Any]],
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
    badge, badge_color, badge_sub = _facade()._surface_audit_badge(results)
    delta_html = ""
    if isinstance(report.get("baseline_delta"), dict):
        delta_md = _facade().baseline_delta_excerpt_markdown(report["baseline_delta"])
        if delta_md.strip():
            delta_html = f"""<p style="margin:10px 0 0;font-size:12px;color:#475569">{_facade().html.escape(delta_md).replace(chr(10), "<br/>")}</p>"""
    overview_html = _facade()._lane_count_overview_html(results)
    html_out = f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 16px"><p style="margin:0 0 10px;font-size:12px;color:{badge_color};font-weight:700">{badge} · {_facade().html.escape(badge_sub)}</p>{overview_html}{lanes_html}{delta_html}</div>'
    return (html_out, report)
