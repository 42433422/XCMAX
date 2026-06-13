"""运营线 O1–O10 健康快照（全景仪表盘 / MODstore 编排可读）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _default_steps() -> dict[str, Any]:
    return {
        "O1": {"status": "done", "note": "获客由官网/SEO承接"},
        "O2": {"status": "partial", "note": "pipeline 未扫描", "pipelines": 0},
        "O3": {"status": "partial", "quoted": 0},
        "O4": {"status": "partial", "note": "支付健康未探测"},
        "O5": {"status": "done"},
        "O6": {"status": "done"},
        "O7": {"status": "partial", "note": "变更工单门户已接 pipeline"},
        "O8": {"status": "partial", "note": "签收 API 已接；存储后端未探测"},
        "O9": {"status": "partial", "note": "财务归档未扫描"},
        "O10": {"status": "partial", "note": "对账调度未运行或未自动确认"},
    }


def _scan_pipelines() -> tuple[int, int, int, dict[str, int]]:
    total = missing_crm = missing_erp = 0
    by_stage: dict[str, int] = {}
    try:
        from app.services.user_cs_pipeline import _STAGE_ORDER, _pipeline_roots

        for root in _pipeline_roots():
            if not root.is_dir():
                continue
            for path in root.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                total += 1
                st = str(data.get("stage") or "idle")
                by_stage[st] = by_stage.get(st, 0) + 1
                rank = _STAGE_ORDER.index(st) if st in _STAGE_ORDER else 0
                if rank >= _STAGE_ORDER.index("intake_done"):
                    if not data.get("crm_opportunity_id"):
                        missing_crm += 1
                    if not data.get("erp_customer_id") and not data.get("erp_customer_name"):
                        missing_erp += 1
    except RECOVERABLE_ERRORS:
        logger.debug("pipeline scan skipped", exc_info=True)
    return total, missing_crm, missing_erp, by_stage


def compute_operations_health() -> dict[str, Any]:
    """基于 pipeline / 支付 / 对账等估算各 O* 健康度；缺模块时降级为 partial。"""
    total, missing_crm, missing_erp, by_stage = _scan_pipelines()
    steps = _default_steps()

    def _status(done: bool, partial: bool) -> str:
        if done:
            return "done"
        if partial:
            return "partial"
        return "blocked"

    o2_partial = total > 0 and (missing_crm > 0 or missing_erp > 0)
    steps["O2"] = {
        "status": _status(not o2_partial, o2_partial or total == 0),
        "missing_crm": missing_crm,
        "missing_erp": missing_erp,
        "pipelines": total,
        "note": None if total else "桌面本地栈无 pipeline 目录",
    }
    steps["O3"] = {
        "status": "partial" if missing_crm else "done",
        "quoted": by_stage.get("quoted", 0) + by_stage.get("negotiating", 0),
    }

    market_payment_health: dict[str, Any] | None = None
    market_base = (os.environ.get("XCAGI_MARKET_BASE_URL") or "").strip().rstrip("/")
    if market_base:
        try:
            import httpx

            resp = httpx.get(
                f"{market_base}/api/health/payment",
                timeout=8.0,
                trust_env=False,
            )
            if resp.status_code < 400 and isinstance(resp.json(), dict):
                market_payment_health = resp.json()
        except RECOVERABLE_ERRORS:
            logger.debug("market payment health probe skipped", exc_info=True)

    pay_backend = (
        os.environ.get("MODEL_PAYMENT_BACKEND") or os.environ.get("PAYMENT_BACKEND") or "python"
    ).strip()
    steps["O4"] = {
        "status": "partial",
        "note": f"MODEL_PAYMENT_BACKEND={pay_backend}",
        "modstore_payment_backend": (market_payment_health or {}).get("payment_backend"),
    }
    if market_payment_health and market_payment_health.get("java_service_healthy"):
        steps["O4"]["status"] = "done"

    try:
        from app.services.user_cs_delivery_signoff import signoff_backend_info

        info = signoff_backend_info()
        backend = str(info.get("backend") or "sqlite")
        steps["O8"] = {
            "status": "done" if backend == "postgres" else "partial",
            "note": info.get("note") or "签收存储",
            **info,
        }
    except RECOVERABLE_ERRORS:
        pass

    try:
        from app.services.reconciliation_scheduler import get_reconciliation_status

        rec = get_reconciliation_status()
        last = rec.get("last_run") if isinstance(rec.get("last_run"), dict) else None
        if last and last.get("success"):
            steps["O10"] = {
                "status": "partial",
                "note": "最近对账周期已执行",
                "auto_confirm_enabled": rec.get("auto_confirm_enabled"),
            }
    except RECOVERABLE_ERRORS:
        pass

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_count": total,
        "steps": steps,
        "breakpoint_count": missing_crm + missing_erp,
        "missing_crm": missing_crm,
        "missing_erp": missing_erp,
        "payment_backend": pay_backend,
        "market_payment_health": market_payment_health,
    }
