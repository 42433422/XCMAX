# mypy: disable-error-code="assignment"
"""平台对账系统 API。

对账报告按时间段汇总以下维度：
  - total_orders / total_gmv：已支付订单数与成交金额
  - platform_revenue：平台抽成收益（来自 AuthorEarning.gross - net 汇总）
  - author_payable：作者应付分润（AuthorEarning.net 汇总）
  - refunds_count / refunds_amount：退款单数与金额
  - wallet_top_ups：钱包充值金额（Transaction txn_type in wallet/alipay_wallet/alipay_recharge）
  - alipay_income：全部支付宝入账（paid orders 总金额）

报告以 ReconciliationReport 快照形式持久化，状态 draft → confirmed。

API 端点（均需管理员权限）：
  POST /api/admin/reconciliation/preview       — **只读** 预览汇总 + `payment-billing-reconciler` skill 对齐 JSON（不落库，供自动化 / RPA 安全触发）
  POST /api/admin/reconciliation/generate    — 生成指定时段对账报告快照并持久化
  GET  /api/admin/reconciliation             — 列出历史报告
  GET  /api/admin/reconciliation/{id}        — 查看单份报告详情
  POST /api/admin/reconciliation/{id}/confirm — 管理员确认报告
  POST /api/internal/reconciliation/preview — 服务间只读预览（含 FHD 宿主 PG/JSON 订单）
  POST /api/internal/reconciliation/run-cycle — 生成报告 + 可选自动确认 + 告警字段
"""

from __future__ import annotations

import csv
import io
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from modstore_server import payment_orders as _po
from modstore_server.api.auth_deps import require_user
from modstore_server.models import (
    ReconciliationReport,
    User,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.reconciliation_snapshot import build_skill_payload as _build_skill_payload
from modstore_server.reconciliation_snapshot import (
    compute_period_snapshot as _compute_period_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reconciliation"])


# ---------------------------------------------------------------- DTOs


class GenerateDTO(BaseModel):
    period_start: str  # ISO 8601 datetime
    period_end: str  # ISO 8601 datetime


class PreviewDTO(BaseModel):
    """只读预览：可选传入 RPA 归集后的支付宝账单总额（CNY），用于与本地聚合粗比。"""

    period_start: str
    period_end: str
    alipay_statement_total_cny: Optional[float] = None


class RunCycleDTO(BaseModel):
    period_start: str
    period_end: str
    alipay_statement_total_cny: Optional[float] = None
    auto_confirm: bool = False
    auto_confirm_max_diff_cny: float = 0.01


def _require_internal_api_key(request: Request) -> None:
    expected = (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or ""
    ).strip()
    if not expected:
        raise HTTPException(status_code=503, detail="internal api not configured")
    got = (request.headers.get("x-internal-api-key") or "").strip()
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail="invalid internal api key")


def _fhd_internal_base() -> str:
    return (
        os.environ.get("XCAGI_FHD_INTERNAL_URL")
        or os.environ.get("FHD_INTERNAL_BASE_URL")
        or os.environ.get("FHD_INTERNAL_URL")
        or ""
    ).rstrip("/")


def _fetch_fhd_host_snapshot(
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    base = _fhd_internal_base()
    key = (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    if not base or not key:
        return {"included": False, "reason": "fhd_internal_not_configured"}
    try:
        resp = httpx.get(
            f"{base}/api/internal/payment/reconciliation-period",
            params={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
            headers={"X-Internal-Api-Key": key},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            return {
                "included": False,
                "reason": f"fhd_http_{resp.status_code}",
                "detail": resp.text[:300],
            }
        data = resp.json()
        if not isinstance(data, dict):
            return {"included": False, "reason": "invalid_fhd_response"}
        snap = data.get("fhd_host_snapshot")
        if not isinstance(snap, dict):
            return {"included": False, "reason": "missing_fhd_host_snapshot"}
        return {"included": True, **snap}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("fetch fhd reconciliation snapshot failed: %s", exc)
        return {
            "included": False,
            "reason": "fhd_fetch_error",
            "detail": str(exc)[:300],
        }


# ---------------------------------------------------------------- 内部工具


def _parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError as exc:
        raise HTTPException(400, f"日期格式错误（期望 ISO 8601）：{s}") from exc


def _report_row(r: ReconciliationReport) -> dict:
    return {
        "id": r.id,
        "period_start": r.period_start.isoformat() if r.period_start else None,
        "period_end": r.period_end.isoformat() if r.period_end else None,
        "total_orders": r.total_orders,
        "total_gmv": r.total_gmv,
        "platform_revenue": r.platform_revenue,
        "author_payable": r.author_payable,
        "refunds_count": r.refunds_count,
        "refunds_amount": r.refunds_amount,
        "wallet_top_ups": r.wallet_top_ups,
        "alipay_income": r.alipay_income,
        "status": r.status,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
    }


def _generate_report(
    session,
    period_start: datetime,
    period_end: datetime,
) -> ReconciliationReport:
    """按时间段汇总并写入 ReconciliationReport 快照。"""
    snap = _compute_period_snapshot(session, period_start, period_end)
    now = datetime.now(UTC).replace(tzinfo=None)
    report = ReconciliationReport(
        period_start=period_start,
        period_end=period_end,
        total_orders=snap["total_orders"],
        total_gmv=snap["total_gmv"],
        platform_revenue=snap["platform_revenue"],
        author_payable=snap["author_payable"],
        refunds_count=snap["refunds_count"],
        refunds_amount=snap["refunds_amount"],
        wallet_top_ups=snap["wallet_top_ups"],
        alipay_income=snap["alipay_income"],
        status="draft",
        generated_at=now,
    )
    session.add(report)
    session.flush()
    return report


def _previous_confirmed_snapshot(session, before: datetime) -> Optional[dict[str, Any]]:
    row = (
        session.query(ReconciliationReport)
        .filter(
            ReconciliationReport.status == "confirmed",
            ReconciliationReport.period_end <= before,
        )
        .order_by(ReconciliationReport.period_end.desc())
        .first()
    )
    if not row:
        return None
    return _report_row(row)


# ---------------------------------------------------------------- API 端点


@router.post("/api/admin/reconciliation/preview")
def api_preview_reconciliation(
    body: PreviewDTO,
    user: User = Depends(require_user),
):
    """管理员只读预览：聚合本地订单/流水/分润，可选叠支付宝账单总额。

    不落库；供 `payment-billing-reconciler` skill、RPA、或 CI 探测安全触发。
    密钥与支付宝开放平台调用仍仅在后端 / Java 服务持有，自动化勿落盘私钥。
    """
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    period_start = _parse_dt(body.period_start)
    period_end = _parse_dt(body.period_end)
    if period_end <= period_start:
        raise HTTPException(400, "period_end 必须晚于 period_start")

    sf = get_session_factory()
    with sf() as session:
        snap = _compute_period_snapshot(session, period_start, period_end)
        prev = _previous_confirmed_snapshot(session, period_start)
        skill = _build_skill_payload(
            snap,
            alipay_statement_total_cny=body.alipay_statement_total_cny,
            previous=prev,
        )
    return {"ok": True, "read_only": True, "payment_reconcile": skill}


@router.post("/api/internal/reconciliation/preview")
def api_internal_preview_reconciliation(
    request: Request,
    body: PreviewDTO,
):
    """服务间只读预览（与 admin preview 相同逻辑，含 FHD 宿主订单）。"""
    _require_internal_api_key(request)
    period_start = _parse_dt(body.period_start)
    period_end = _parse_dt(body.period_end)
    if period_end <= period_start:
        raise HTTPException(400, "period_end 必须晚于 period_start")
    sf = get_session_factory()
    with sf() as session:
        snap = _compute_period_snapshot(session, period_start, period_end)
        prev = _previous_confirmed_snapshot(session, period_start)
        skill = _build_skill_payload(
            snap,
            alipay_statement_total_cny=body.alipay_statement_total_cny,
            previous=prev,
        )
    return {"ok": True, "read_only": True, "payment_reconcile": skill}


@router.post("/api/internal/reconciliation/run-cycle")
def api_internal_run_reconciliation_cycle(
    request: Request,
    body: RunCycleDTO,
):
    """生成 draft 报告；``auto_confirm`` 且差异在阈值内时自动 confirmed。"""
    _require_internal_api_key(request)
    period_start = _parse_dt(body.period_start)
    period_end = _parse_dt(body.period_end)
    if period_end <= period_start:
        raise HTTPException(400, "period_end 必须晚于 period_start")

    sf = get_session_factory()
    with sf() as session:
        report = _generate_report(session, period_start, period_end)
        snap = _compute_period_snapshot(session, period_start, period_end)
        prev = _previous_confirmed_snapshot(session, period_start)
        skill = _build_skill_payload(
            snap,
            alipay_statement_total_cny=body.alipay_statement_total_cny,
            previous=prev,
        )
        session.commit()
        session.refresh(report)

    auto_confirmed = False
    alert_message: Optional[str] = None
    skill_status = str(skill.get("status") or "ok")
    diff_abs = abs(float(skill.get("diff_amount_cny") or 0))

    if body.auto_confirm:
        if skill_status == "ok" and diff_abs <= float(body.auto_confirm_max_diff_cny):
            now = datetime.now(UTC).replace(tzinfo=None)
            with sf() as session:
                row = (
                    session.query(ReconciliationReport)
                    .filter(ReconciliationReport.id == report.id)
                    .first()
                )
                if row and row.status == "draft":
                    row.status = "confirmed"
                    row.confirmed_at = now
                    session.commit()
                    auto_confirmed = True
        else:
            alert_message = (
                f"自动确认跳过: status={skill_status} diff={diff_abs:.2f} "
                f"max={body.auto_confirm_max_diff_cny}"
            )
    elif skill_status != "ok":
        alert_message = f"对账预警: status={skill_status} diff={diff_abs:.2f}"

    return {
        "ok": True,
        "report_id": report.id,
        "report": _report_row(report),
        "payment_reconcile": skill,
        "auto_confirmed": auto_confirmed,
        "alert_message": alert_message,
    }


@router.post("/api/admin/reconciliation/generate")
def api_generate_report(
    body: GenerateDTO,
    user: User = Depends(require_user),
):
    """管理员按时段生成对账报告快照（幂等：不校验重复，允许重新生成）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    period_start = _parse_dt(body.period_start)
    period_end = _parse_dt(body.period_end)
    if period_end <= period_start:
        raise HTTPException(400, "period_end 必须晚于 period_start")

    sf = get_session_factory()
    with sf() as session:
        report = _generate_report(session, period_start, period_end)
        session.commit()
        session.refresh(report)
        return {"ok": True, "report": _report_row(report)}


@router.get("/api/admin/reconciliation")
def api_list_reports(
    status: Optional[str] = Query(None, description="draft/confirmed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: User = Depends(require_user),
):
    """管理员列出历史对账报告（按生成时间倒序）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    sf = get_session_factory()
    with sf() as session:
        q = session.query(ReconciliationReport)
        if status:
            q = q.filter(ReconciliationReport.status == status)
        total = q.count()
        rows = (
            q.order_by(ReconciliationReport.generated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "ok": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_report_row(r) for r in rows],
        }


@router.get("/api/admin/reconciliation/{report_id}")
def api_get_report(
    report_id: int,
    export_csv: bool = Query(False, description="是否导出订单明细 CSV"),
    user: User = Depends(require_user),
):
    """管理员查看单份报告详情，可选导出订单级 CSV。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    sf = get_session_factory()
    with sf() as session:
        report = (
            session.query(ReconciliationReport).filter(ReconciliationReport.id == report_id).first()
        )
        if not report:
            raise HTTPException(404, "对账报告不存在")

        if not export_csv:
            return {"ok": True, "report": _report_row(report)}

        # 导出订单级 CSV
        period_start = report.period_start
        period_end = report.period_end
        all_orders, _ = _po.list_orders(status="paid", limit=100_000)
        rows_in_range = []
        for o in all_orders:
            raw_ts = o.get("paid_at") or o.get("created_at") or ""
            try:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).replace(tzinfo=None)
            except RECOVERABLE_ERRORS:
                continue
            if period_start <= ts < period_end:
                rows_in_range.append(o)

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "out_trade_no",
                "user_id",
                "total_amount",
                "kind",
                "status",
                "paid_at",
                "refunded",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for o in rows_in_range:
            writer.writerow(
                {
                    "out_trade_no": o.get("out_trade_no", ""),
                    "user_id": o.get("user_id", ""),
                    "total_amount": o.get("total_amount", ""),
                    "kind": o.get("kind", ""),
                    "status": o.get("status", ""),
                    "paid_at": o.get("paid_at") or o.get("created_at", ""),
                    "refunded": o.get("refunded", False),
                }
            )
        buf.seek(0)
        filename = (
            f"reconciliation_{report_id}_"
            f"{period_start.strftime('%Y%m%d')}_{period_end.strftime('%Y%m%d')}.csv"
        )
        return StreamingResponse(
            iter([buf.read()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/api/admin/reconciliation/{report_id}/confirm")
def api_confirm_report(
    report_id: int,
    user: User = Depends(require_user),
):
    """管理员确认对账报告（draft → confirmed）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    now = datetime.now(UTC).replace(tzinfo=None)
    sf = get_session_factory()
    with sf() as session:
        report = (
            session.query(ReconciliationReport).filter(ReconciliationReport.id == report_id).first()
        )
        if not report:
            raise HTTPException(404, "对账报告不存在")
        if report.status != "draft":
            raise HTTPException(400, f"报告当前状态为 {report.status}，无法重复确认")
        report.status = "confirmed"
        report.confirmed_at = now
        session.commit()
        return {"ok": True, "report_id": report_id, "status": "confirmed"}


__all__ = ["router"]
