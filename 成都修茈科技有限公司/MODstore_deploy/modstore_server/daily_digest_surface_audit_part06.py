# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def lane_employee_ids(lane: str, *, limit: int = 6) -> _facade().List[str]:
    """三端 lane 对应的在岗员工 pkg_id 列表（去重，保持顺序）。

    优先从 :data:`duty_roster.SIX_LINE_DEPARTMENTS` 解析对应部门所有子区员工；
    解析失败或 P-App（无独立部门）回退到 :data:`_LANE_OWNER_FALLBACK`。
    """
    out: _facade().List[str] = []

    def _push(pid: str) -> None:
        pid = str(pid or "").strip()
        if pid and pid not in out:
            out.append(pid)

    dept_key = _facade()._LANE_TO_DEPARTMENT.get(lane)
    if dept_key:
        try:
            from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS

            dept = SIX_LINE_DEPARTMENTS.get(dept_key) or {}
            subzones = dept.get("subzones") if isinstance(dept.get("subzones"), dict) else {}
            for sz in subzones.values():
                for pid in sz.get("ids") or [] if isinstance(sz, dict) else []:
                    _push(pid)
        except Exception:
            _facade().logger.debug("surface audit: lane_employee_ids fallback lane=%s", lane)
    for pid in _facade()._LANE_OWNER_FALLBACK.get(lane, []):
        _push(pid)
    return out[: max(1, limit)]


def _rule_based_lane_analysis(
    lane: str, rows: _facade().List[_facade().Dict[str, _facade().Any]]
) -> str:
    """bench LLM 不可用时的规则化分析（只陈述 HTTP / console 事实，不臆造）。"""
    if not rows:
        return "本产线本次无巡检页面。"
    ok = [r for r in rows if (r.get("status") or 0) < 400 and (not r.get("error"))]
    bad = [r for r in rows if r not in ok]
    ce_total = sum((len(r.get("console_errors") or []) for r in rows))
    parts = [f"巡检 {len(rows)} 页，正常 {len(ok)} 页"]
    if bad:
        names = "、".join((str(r.get("name") or r.get("url") or "?") for r in bad[:4]))
        parts.append(f"异常 {len(bad)} 页（{names}）")
    if ce_total:
        parts.append(f"console 报错累计 {ce_total} 条，建议排查前端脚本")
    if not bad and (not ce_total):
        parts.append("HTTP 与 console 均无异常")
    return "；".join(parts) + "。"


def _surface_analysis_timeout_sec() -> float:
    raw = (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_ANALYSIS_TIMEOUT_SEC") or "90").strip()
    try:
        return max(10.0, min(600.0, float(raw)))
    except ValueError:
        return 90.0


def _build_lane_analysis_user_content(
    lane: str, lane_label: str, rows: _facade().List[_facade().Dict[str, _facade().Any]]
) -> str:
    lines: _facade().List[str] = []
    for r in rows:
        ce = r.get("console_errors") or []
        ce_part = "；console: " + " | ".join((str(x)[:160] for x in ce[:3])) if ce else ""
        err_part = f"；抓取错误: {r.get('error')}" if r.get("error") else ""
        lines.append(
            f"- {r.get('name')}（{r.get('viewport')}）｜URL {r.get('url')}｜HTTP {r.get('status') or '—'}｜标题「{str(r.get('title') or '')[:80]}」{ce_part}{err_part}"
        )
    return (
        f"产线：{lane}（{lane_label}）。以下是本次 Playwright 巡检到的关键页面（截图已另存）：\n"
        + "\n".join(lines)
    )
