"""对账定时任务：MODstore reconciliation + FHD 宿主订单 + 可选自动确认与告警。"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import httpx

from app.services.fhd_payment_reconciliation import (
    default_reconciliation_period,
    load_last_reconciliation_run,
    save_reconciliation_run,
)

logger = logging.getLogger(__name__)


def _market_base() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "").rstrip("/")


def _internal_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def _auto_confirm_enabled() -> bool:
    return (os.environ.get("RECONCILIATION_AUTO_CONFIRM") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _auto_confirm_max_diff() -> float:
    try:
        return float(os.environ.get("RECONCILIATION_AUTO_CONFIRM_MAX_DIFF_CNY") or "0.01")
    except ValueError:
        return 0.01


def _alert_webhook() -> str:
    return (os.environ.get("RECONCILIATION_ALERT_WEBHOOK") or "").strip()


def run_scheduled_reconciliation(*, dry_run: bool = True) -> dict[str, Any]:
    """兼容旧调用：dry_run=True 仅预览，False 走完整闭环（生成+可选自动确认）。"""
    if dry_run:
        return run_reconciliation_preview_cycle()
    return run_reconciliation_full_cycle()


def run_reconciliation_preview_cycle(
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    alipay_statement_total_cny: float | None = None,
) -> dict[str, Any]:
    base = _market_base()
    key = _internal_key()
    if not base or not key:
        return {"ok": False, "error": "XCAGI_MARKET_BASE_URL or internal api key not set"}
    start, end = period_start, period_end
    if start is None or end is None:
        start, end = default_reconciliation_period()
    body: dict[str, Any] = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }
    if alipay_statement_total_cny is not None:
        body["alipay_statement_total_cny"] = alipay_statement_total_cny
    try:
        resp = httpx.post(
            f"{base}/api/internal/reconciliation/preview",
            json=body,
            headers={"X-Internal-Api-Key": key, "Content-Type": "application/json"},
            timeout=90.0,
        )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return {
            "ok": resp.status_code < 400,
            "status_code": resp.status_code,
            "dry_run": True,
            "data": data,
        }
    except Exception as exc:
        logger.exception("reconciliation preview failed")
        return {"ok": False, "error": str(exc)}


def run_reconciliation_full_cycle(
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    alipay_statement_total_cny: float | None = None,
    auto_confirm: bool | None = None,
) -> dict[str, Any]:
    """生成对账报告；在配置允许且差异在阈值内时自动 confirmed，并触发告警。"""
    base = _market_base()
    key = _internal_key()
    if not base or not key:
        return {"ok": False, "error": "XCAGI_MARKET_BASE_URL or internal api key not set"}
    start, end = period_start, period_end
    if start is None or end is None:
        start, end = default_reconciliation_period()
    do_confirm = _auto_confirm_enabled() if auto_confirm is None else bool(auto_confirm)
    body: dict[str, Any] = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "auto_confirm": do_confirm,
        "auto_confirm_max_diff_cny": _auto_confirm_max_diff(),
    }
    if alipay_statement_total_cny is not None:
        body["alipay_statement_total_cny"] = alipay_statement_total_cny
    try:
        resp = httpx.post(
            f"{base}/api/internal/reconciliation/run-cycle",
            json=body,
            headers={"X-Internal-Api-Key": key, "Content-Type": "application/json"},
            timeout=120.0,
        )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        ok = resp.status_code < 400 and bool(data.get("ok", False))
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "ok": ok,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "auto_confirm": do_confirm,
            "response": data,
        }
        save_reconciliation_run(record)
        if ok:
            _maybe_emit_reconciliation_alert(data)
        return {"ok": ok, "status_code": resp.status_code, "dry_run": False, "data": data}
    except Exception as exc:
        logger.exception("reconciliation full cycle failed")
        return {"ok": False, "error": str(exc)}


def _maybe_emit_reconciliation_alert(payload: dict[str, Any]) -> None:
    skill = payload.get("payment_reconcile") if isinstance(payload, dict) else {}
    if not isinstance(skill, dict):
        skill = {}
    status = str(skill.get("status") or "ok")
    diff = float(skill.get("diff_amount_cny") or 0)
    auto_confirmed = bool(payload.get("auto_confirmed"))
    needs_alert = status != "ok" or (not auto_confirmed and payload.get("report_id"))

    if not needs_alert:
        return

    from app.services.operations_line_bridge import emit_operations_event

    emit_operations_event(
        "O10",
        "alert",
        {
            "reconciliation_status": status,
            "diff_amount_cny": diff,
            "report_id": payload.get("report_id"),
            "auto_confirmed": auto_confirmed,
            "message": payload.get("alert_message") or "对账需人工关注",
        },
    )
    webhook = _alert_webhook()
    if not webhook:
        return
    try:
        httpx.post(
            webhook,
            json={
                "source": "fhd-reconciliation",
                "status": status,
                "diff_amount_cny": diff,
                "report_id": payload.get("report_id"),
                "report_md": skill.get("report_md"),
            },
            timeout=10.0,
        )
    except Exception:
        logger.warning("reconciliation alert webhook failed", exc_info=True)


def get_reconciliation_status() -> dict[str, Any]:
    last = load_last_reconciliation_run()
    auto = _auto_confirm_enabled()
    out: dict[str, Any] = {
        "auto_confirm_enabled": auto,
        "last_run": last,
    }
    if last:
        resp = last.get("response") if isinstance(last.get("response"), dict) else {}
        out["last_ok"] = bool(last.get("ok"))
        out["last_auto_confirmed"] = bool(resp.get("auto_confirmed"))
        out["last_report_id"] = resp.get("report_id")
    return out


def import_bank_statement_csv(content: str) -> list[dict[str, Any]]:
    """解析银行流水 CSV：date,amount,reference,description"""
    reader = csv.DictReader(StringIO(content))
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append(
            {
                "date": (row.get("date") or row.get("交易日期") or "").strip(),
                "amount": (row.get("amount") or row.get("金额") or "").strip(),
                "reference": (row.get("reference") or row.get("流水号") or "").strip(),
                "description": (row.get("description") or row.get("摘要") or "").strip(),
            }
        )
    return rows
