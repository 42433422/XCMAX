"""运营线 O1–O10 事件桥：Pipeline/CRM/支付/签收 → orchestrator 可观测。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_LOG = "operations_line_events.jsonl"


def _event_log_path() -> Path:
    from app.utils.path_utils import get_base_dir, get_data_dir

    for base in (
        Path(get_data_dir()) / "customer_service",
        Path(get_base_dir()) / "data" / "customer_service",
    ):
        base.mkdir(parents=True, exist_ok=True)
        return base / _EVENT_LOG
    p = Path(get_data_dir()) / "customer_service"
    p.mkdir(parents=True, exist_ok=True)
    return p / _EVENT_LOG


def emit_operations_event(step_id: str, status: str, payload: dict[str, Any] | None = None) -> None:
    """追加本地事件日志；若配置 MODSTORE 则 POST internal hook。"""
    entry = {
        "step_id": step_id,
        "status": status,
        "payload": payload or {},
        "at": datetime.now(timezone.utc).isoformat(),
    }
    path = _event_log_path()
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("operations_line event log write failed")

    base = (os.environ.get("XCAGI_MARKET_BASE_URL") or "").rstrip("/")
    secret = (os.environ.get("XCAGI_OPS_LINE_HOOK_SECRET") or "").strip()
    if not base:
        return
    try:
        import httpx

        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Ops-Line-Secret"] = secret
        httpx.post(
            f"{base}/api/admin/production-line/event",
            json=entry,
            headers=headers,
            timeout=5.0,
        )
    except Exception:
        logger.debug("operations_line remote hook skipped", exc_info=True)


def pipeline_stage_to_ops_step(stage: str) -> str | None:
    mapping = {
        "idle": "O1",
        "connected": "O1",
        "intake": "O2",
        "intake_done": "O2",
        "quoted": "O3",
        "negotiating": "O3",
        "contract_pending": "O3",
        "signed": "O4",
        "delivering": "O5",
        "delivered": "O8",
    }
    return mapping.get(stage)


def on_pipeline_saved(doc: dict[str, Any]) -> None:
    stage = str(doc.get("stage") or "idle")
    step = pipeline_stage_to_ops_step(stage)
    if not step:
        return
    emit_operations_event(
        step,
        "progress",
        {
            "market_user_id": doc.get("market_user_id"),
            "crm_opportunity_id": doc.get("crm_opportunity_id"),
            "stage": stage,
        },
    )


def _o8_signoff_step() -> dict[str, Any]:
    try:
        from app.services.user_cs_delivery_signoff import signoff_backend_info

        info = signoff_backend_info()
        backend = str(info.get("backend") or "sqlite")
        if backend == "postgres":
            return {
                "status": "done",
                "note": "签收记录 PostgreSQL cs_delivery_signoffs",
                **info,
            }
        return {
            "status": "partial",
            "note": "签收仍为 SQLite；生产请 CS_SIGNOFF_BACKEND=postgres + alembic upgrade",
            **info,
        }
    except Exception:
        return {"status": "partial", "note": "签收 API 已接；存储后端未探测"}


def _o4_payment_step(
    *,
    pay_backend: str,
    json_migration_pending: bool,
    market_payment_health: dict[str, Any] | None,
) -> dict[str, Any]:
    host_ok = pay_backend.lower() in ("modstore", "java", "postgres", "postgresql", "pg")
    step: dict[str, Any] = {
        "status": "done" if host_ok and not json_migration_pending else "partial",
        "note": f"MODEL_PAYMENT_BACKEND={pay_backend}",
        "json_migration_pending": json_migration_pending,
    }
    if market_payment_health:
        step["modstore_payment_backend"] = market_payment_health.get("payment_backend")
        step["java_service_healthy"] = market_payment_health.get("java_service_healthy")
        step["ready_for_java_cutover"] = market_payment_health.get("ready_for_java_cutover")
        mod_backend = str(market_payment_health.get("payment_backend") or "").lower()
        if pay_backend.lower() == "modstore" and mod_backend == "java":
            if market_payment_health.get("java_service_healthy"):
                step["status"] = "done" if not json_migration_pending else "partial"
                step["note"] = "市场支付已切 Java SoT"
            else:
                step["status"] = "partial"
                step["note"] = "PAYMENT_BACKEND=java 但 Java 支付服务未就绪"
        elif pay_backend.lower() == "modstore" and mod_backend == "python":
            step["status"] = "partial"
            step["note"] = "市场仍为 PAYMENT_BACKEND=python，待 Java 直切"
    return step


def compute_operations_health() -> dict[str, Any]:
    """基于 pipeline 目录与 CRM 库估算各 O* 健康度。"""
    from app.services.user_cs_pipeline import _STAGE_ORDER, _pipeline_roots

    roots = _pipeline_roots()
    total = 0
    missing_crm = 0
    missing_erp = 0
    by_stage: dict[str, int] = {}
    for root in roots:
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

    def _status(done: bool, partial: bool) -> str:
        if done:
            return "done"
        if partial:
            return "partial"
        return "blocked"

    o2_partial = total > 0 and (missing_crm > 0 or missing_erp > 0)
    import os

    market_payment_health: dict[str, Any] | None = None
    market_base = (os.environ.get("XCAGI_MARKET_BASE_URL") or "").rstrip("/")
    if market_base:
        try:
            import httpx

            resp = httpx.get(f"{market_base}/api/health/payment", timeout=8.0)
            if resp.status_code < 400:
                payload = resp.json()
                if isinstance(payload, dict):
                    market_payment_health = payload
        except Exception:
            logger.debug("market payment health probe skipped", exc_info=True)

    pay_backend = (
        os.environ.get("MODEL_PAYMENT_BACKEND") or os.environ.get("PAYMENT_BACKEND") or "python"
    ).strip()
    json_migration_pending = False
    try:
        from app.infrastructure.payment.order_store import json_store_has_unmigrated_orders

        json_migration_pending = json_store_has_unmigrated_orders()
    except Exception:
        pass
    ext_provider = (os.environ.get("EXTERNAL_CRM_PROVIDER") or "").strip()
    external_crm_configured = bool(ext_provider)
    external_crm_status: dict[str, Any] = {}
    try:
        from app.services.external_crm_adapter import external_crm_status as _crm_status

        external_crm_status = _crm_status()
        external_crm_configured = bool(external_crm_status.get("configured"))
    except Exception:
        external_crm_status = {
            "salesforce_implemented": True,
            "configured": external_crm_configured,
        }
    steps = {
        "O1": {"status": "done", "note": "获客由官网/SEO承接"},
        "O2": {
            "status": _status(not o2_partial, o2_partial),
            "missing_crm": missing_crm,
            "missing_erp": missing_erp,
            "pipelines": total,
            "external_crm": external_crm_status,
            "note": (
                external_crm_status.get("note") if isinstance(external_crm_status, dict) else None
            ),
        },
        "O3": {
            "status": "partial" if missing_crm else "done",
            "quoted": by_stage.get("quoted", 0) + by_stage.get("negotiating", 0),
        },
        "O4": _o4_payment_step(
            pay_backend=pay_backend,
            json_migration_pending=json_migration_pending,
            market_payment_health=market_payment_health,
        ),
        "O5": {"status": "done"},
        "O6": {"status": "done"},
        "O7": {"status": "partial", "note": "变更工单门户已接 pipeline"},
        "O8": _o8_signoff_step(),
        "O9": {"status": "partial"},
        "O10": {"status": "partial", "note": "对账调度未运行或未自动确认"},
    }
    try:
        from app.services.reconciliation_scheduler import get_reconciliation_status

        rec = get_reconciliation_status()
        last = rec.get("last_run") if isinstance(rec.get("last_run"), dict) else None
        if last and last.get("ok"):
            resp = last.get("response") if isinstance(last.get("response"), dict) else {}
            if (
                resp.get("auto_confirmed")
                or str((resp.get("payment_reconcile") or {}).get("status")) == "ok"
            ):
                steps["O10"] = {
                    "status": "done" if resp.get("auto_confirmed") else "partial",
                    "note": "最近对账周期已执行",
                    "last_report_id": resp.get("report_id"),
                    "auto_confirm_enabled": rec.get("auto_confirm_enabled"),
                }
            else:
                steps["O10"] = {
                    "status": "partial",
                    "note": "最近对账存在差异或未自动确认",
                    "last_report_id": resp.get("report_id"),
                    "auto_confirm_enabled": rec.get("auto_confirm_enabled"),
                }
        else:
            steps["O10"]["auto_confirm_enabled"] = rec.get("auto_confirm_enabled")
    except Exception:
        pass
    try:
        from app.services.finance_unified_archive import compute_finance_archive_coverage

        fin = compute_finance_archive_coverage()
        cov = float(fin.get("finance_archive_coverage") or 0)
        need = int(fin.get("finance_archive_need") or 0)
        o9_status = "done" if need == 0 or cov >= 1.0 else ("partial" if cov > 0 else "partial")
        steps["O9"] = {
            "status": o9_status,
            "note": "XCAGI 自建财务闭环（不接入用友/金蝶）",
            **fin,
        }
    except Exception:
        steps["O9"] = {
            "status": "partial",
            "note": "finance_unified_archive unavailable",
            "finance_self_hosted": True,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_count": total,
        "steps": steps,
        "breakpoint_count": missing_crm + missing_erp,
        "missing_crm": missing_crm,
        "missing_erp": missing_erp,
        "external_crm_configured": external_crm_configured,
        "external_crm_provider": ext_provider or None,
        "external_crm_status": external_crm_status,
        "payment_backend": pay_backend,
        "market_payment_health": market_payment_health,
    }
