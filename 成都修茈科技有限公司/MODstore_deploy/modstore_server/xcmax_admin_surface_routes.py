# ruff: noqa
"""XCmax daily-digest, release, identity, and surface-audit routes."""
from __future__ import annotations
import importlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("modstore_server.xcmax_admin_api")
router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])


def _facade():
    return importlib.import_module("modstore_server.xcmax_admin_api")


def _daily_digest_record_to_dict(row: Any, *, include_body: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "day": row.day,
        "subject": row.subject,
        "body_text": row.body_text,
        "meeting_minutes_html": row.meeting_minutes_html,
        "recipients": json.loads(row.recipients_json or "[]"),
        "delivery": json.loads(row.delivery_json or "[]"),
        "delivered": bool(row.delivered),
        "source": row.source,
        "release_train_before": getattr(row, "release_train_before", "") or "",
        "release_train_after": getattr(row, "release_train_after", "") or "",
        "release_kind": getattr(row, "release_kind", "") or "",
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else "",
    }
    if include_body:
        data["body_html"] = row.body_html
    return data


@router.get("/admin/daily-digests", response_model=None)
async def xcmax_daily_digest_records(
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            total = session.query(DailyDigestRecord.id).count()
            rows = (
                session.query(DailyDigestRecord)
                .order_by(DailyDigestRecord.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "success": True,
                "data": [
                    _facade()._daily_digest_record_to_dict(r, include_body=False) for r in rows
                ],
                "total": total,
            }
    except Exception as exc:
        _facade().logger.warning("xcmax daily-digests list failed: %s", exc)
        return {"success": True, "data": [], "total": 0, "note": str(exc)}


@router.get("/admin/daily-digests/{record_id}", response_model=None)
async def xcmax_daily_digest_record_detail(record_id: int) -> dict[str, Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, record_id)
            if row is None:
                return _facade().JSONResponse(
                    {"success": False, "message": "not found"}, status_code=404
                )
            return {
                "success": True,
                "data": _facade()._daily_digest_record_to_dict(row, include_body=True),
            }
    except Exception as exc:
        _facade().logger.warning("xcmax daily-digests detail failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/release-train", response_model=None)
async def xcmax_release_train() -> dict[str, Any]:
    """release_train 四段 SSOT（与 FHD 全景页 / 运维台 live 刷新同源）。"""
    try:
        from modstore_server.release_train import snapshot_public

        return {"success": True, "data": snapshot_public()}
    except Exception as exc:
        _facade().logger.warning("xcmax release-train failed: %s", exc)
        return {"success": True, "data": {"current": "1.0.0.0", "day_index": 0, "note": str(exc)}}


@router.get("/admin/digest-identity", response_model=None)
async def xcmax_digest_identity() -> dict[str, Any]:
    """返回当前宜向 XCmax 展示的 6 位身份校验码及是否仍可通过市场管理端解锁校验。

    与 ``POST /api/auth/verify-admin-digest-code`` 共用
    :mod:`modstore_server.digest_identity` 实现，保证本地页眉与修茈市场解锁口径一致。
    """
    try:
        from modstore_server.digest_identity import resolve_digest_identity_for_xcmax
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            data = resolve_digest_identity_for_xcmax(session)
        display_base = (
            (
                _facade().os.environ.get("MODSTORE_DIGEST_DISPLAY_API_BASE")
                or _facade().os.environ.get("MODSTORE_PUBLIC_ORIGIN")
                or ""
            )
            .strip()
            .rstrip("/")
        )
        if display_base:
            data = dict(data)
            data["digest_api_base"] = display_base
        return {"success": True, "data": data}
    except Exception as exc:
        _facade().logger.warning("xcmax digest-identity failed: %s", exc)
        return {
            "success": False,
            "message": str(exc),
            "data": {"code": "", "expires_at": "", "valid": False, "daily_digest_id": None},
        }


@router.get("/admin/surface-audit/lane", response_model=None)
async def xcmax_surface_audit_lane(
    lane: str = Query("P-W"), refresh: bool = Query(False)
) -> dict[str, Any]:
    """P-W / P-S / P-App 截图+分析快照（对应时间轨 SW / SS / SA 节点）。"""
    import base64

    lane = (lane or "P-W").strip()
    workflow_nodes = {"P-W": "SW", "P-S": "SS", "P-App": "SA"}
    try:
        from modstore_server.daily_digest_surface_audit import (
            _base_url,
            _save_dir,
            lane_employee_ids,
            run_surface_audit_async,
        )
    except ImportError as exc:
        return _facade().JSONResponse(
            {"success": False, "message": f"daily_digest_surface_audit 未安装: {exc}"},
            status_code=501,
        )
    try:
        from modstore_server.daily_digest import digest_calendar_day

        day = digest_calendar_day()
    except Exception:
        day = _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")

    async def _lane_payload(
        report: dict[str, _facade().Any], *, cached: bool
    ) -> dict[str, _facade().Any]:
        la = {}
        lane_analysis = report.get("lane_analysis")
        if isinstance(lane_analysis, dict):
            row = lane_analysis.get(lane)
            if isinstance(row, dict):
                la = row
        pages: list[dict[str, Any]] = []
        for row in report.get("results") if isinstance(report.get("results"), list) else []:
            if row.get("lane") != lane:
                continue
            thumb_b64 = ""
            saved = str(row.get("screenshot_saved") or "").strip()
            if saved:
                p = _facade().Path(saved)
                if p.is_file():
                    raw = p.read_bytes()
                    if len(raw) <= 1600000:
                        thumb_b64 = base64.b64encode(raw).decode("ascii")
            pages.append(
                {
                    "name": row.get("name"),
                    "url": row.get("url"),
                    "status": row.get("status"),
                    "title": row.get("title"),
                    "viewport": row.get("viewport"),
                    "console_errors": row.get("console_errors") or [],
                    "error": row.get("error"),
                    "screenshot_b64": thumb_b64,
                    "screenshot_saved": saved,
                }
            )
        return {
            "lane": lane,
            "lane_label": {"P-W": "网站", "P-S": "软件", "P-App": "App"}.get(lane, lane),
            "workflow_node": workflow_nodes.get(lane, ""),
            "day": day,
            "base_url": _base_url(),
            "cached": cached,
            "ok": bool(report.get("ok")),
            "skipped": bool(report.get("skipped")),
            "error": report.get("error") or "",
            "pages": pages,
            "analysis": la,
            "owners": la.get("owners") or lane_employee_ids(lane),
        }

    if refresh:
        try:
            report = await run_surface_audit_async()
            return {"success": True, "data": await _lane_payload(report, cached=False)}
        except Exception as exc:
            _facade().logger.warning("surface audit refresh failed lane=%s: %s", lane, exc)
            return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    save_root = _save_dir(day)
    if save_root is None or not save_root.is_dir():
        return {
            "success": True,
            "data": {
                "lane": lane,
                "workflow_node": workflow_nodes.get(lane, ""),
                "day": day,
                "cached": True,
                "ok": False,
                "pages": [],
                "analysis": {},
                "owners": lane_employee_ids(lane),
                "error": "今日尚未巡检或未配置截图保存目录",
            },
        }
    pages: list[dict[str, Any]] = []
    for png in sorted(save_root.glob("*.png")):
        if f"_{lane}_" not in png.name:
            continue
        slug_parts = png.stem.split("_", 2)
        name = slug_parts[2] if len(slug_parts) >= 3 else png.stem
        base = _base_url()
        path_guess = "/" if "首页" in name else f"/{name}"
        raw = png.read_bytes()
        thumb_b64 = base64.b64encode(raw).decode("ascii") if len(raw) <= 480000 else ""
        pages.append(
            {
                "lane": lane,
                "name": name,
                "url": f"{base}{path_guess}",
                "status": 200,
                "title": name,
                "viewport": "desktop",
                "console_errors": [],
                "error": None,
                "screenshot_b64": thumb_b64,
                "screenshot_saved": str(png),
            }
        )
    report_stub = {"ok": bool(pages), "results": pages, "lane_analysis": {}}
    return {"success": True, "data": await _lane_payload(report_stub, cached=True)}
