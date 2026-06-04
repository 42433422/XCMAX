"""FHD 宿主侧模型支付订单对账聚合（PostgreSQL + legacy JSON，供 MODstore 合并）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def _order_paid_ts(order: dict[str, Any]) -> datetime | None:
    raw = order.get("paid_at") or order.get("created_at") or order.get("updated_at")
    return _parse_dt(str(raw) if raw else "")


def _order_amount_yuan(order: dict[str, Any]) -> float:
    if order.get("amount_yuan") is not None:
        try:
            return float(order["amount_yuan"])
        except (TypeError, ValueError):
            pass
    try:
        return int(order.get("amount_cents") or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _iter_json_file_orders() -> list[dict[str, Any]]:
    from app.infrastructure.payment import order_store_json as _json

    p = _json.order_store_path()
    if not p.is_file():
        return []
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("fhd json orders read failed: %s", exc)
        return []
    orders = data.get("orders") if isinstance(data, dict) else {}
    if not isinstance(orders, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, row in orders.items():
        if not isinstance(row, dict):
            continue
        snap = dict(row)
        snap.setdefault("out_trade_no", key)
        snap["source"] = "fhd_json"
        out.append(snap)
    return out


def _iter_pg_orders() -> list[dict[str, Any]]:
    from app.db.models.model_payment import ModelPaymentOrder
    from app.db.session import get_db

    with get_db() as db:
        rows = db.query(ModelPaymentOrder).filter(ModelPaymentOrder.status == "paid").all()
    return [{**r.to_snapshot(), "source": "fhd_postgres"} for r in rows]


def list_fhd_paid_orders_for_period(
    period_start: datetime,
    period_end: datetime,
    *,
    include_legacy_json: bool = True,
) -> list[dict[str, Any]]:
    """区间内已支付订单；PG 与 JSON 按 out_trade_no 去重（PG 优先）。"""
    by_trade: dict[str, dict[str, Any]] = {}

    try:
        from app.infrastructure.payment.payment_sot import is_fhd_postgres_payment_sot

        if is_fhd_postgres_payment_sot():
            for o in _iter_pg_orders():
                by_trade[str(o.get("out_trade_no") or "")] = o
    except Exception:
        logger.debug("pg reconciliation list skipped", exc_info=True)

    if include_legacy_json:
        for o in _iter_json_file_orders():
            key = str(o.get("out_trade_no") or "")
            if key and key not in by_trade:
                by_trade[key] = o

    if not by_trade:
        try:
            from app.infrastructure.payment.payment_sot import is_json_legacy_payment_sot

            if is_json_legacy_payment_sot():
                for o in _iter_json_file_orders():
                    key = str(o.get("out_trade_no") or "")
                    if key:
                        by_trade[key] = o
        except Exception:
            pass

    paid: list[dict[str, Any]] = []
    for o in by_trade.values():
        if str(o.get("status") or "").lower() != "paid":
            continue
        ts = _order_paid_ts(o)
        if ts is None or not (period_start <= ts < period_end):
            continue
        paid.append(o)
    return paid


def compute_fhd_period_snapshot(
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    orders = list_fhd_paid_orders_for_period(period_start, period_end)
    total_gmv = round(sum(_order_amount_yuan(o) for o in orders), 2)
    by_source: dict[str, int] = {}
    for o in orders:
        src = str(o.get("source") or "fhd")
        by_source[src] = by_source.get(src, 0) + 1
    return {
        "total_orders": len(orders),
        "total_gmv": total_gmv,
        "refunds_count": 0,
        "refunds_amount": 0.0,
        "orders_sample": [
            {
                "out_trade_no": o.get("out_trade_no"),
                "amount_yuan": _order_amount_yuan(o),
                "paid_at": o.get("paid_at"),
                "source": o.get("source"),
                "market_user_id": o.get("market_user_id"),
            }
            for o in orders[:50]
        ],
        "by_source": by_source,
        "backend": _payment_backend_label(),
    }


def _payment_backend_label() -> str:
    try:
        from app.infrastructure.payment.payment_sot import model_payment_backend

        return model_payment_backend()
    except Exception:
        return "unknown"


def default_reconciliation_period() -> tuple[datetime, datetime]:
    """上一自然日 [00:00, 24:00) UTC。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    return start, end


def _last_run_path() -> Path:
    from app.utils.path_utils import get_data_dir

    p = Path(get_data_dir()) / "reconciliation_last_run.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_reconciliation_run(record: dict[str, Any]) -> None:
    path = _last_run_path()
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_reconciliation_run() -> dict[str, Any] | None:
    path = _last_run_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
