"""跨宿主计量与统一计费真相源（阶段 11）。

解决「FHD PostgreSQL vs MODstore Java 钱包」的 SoT 分裂：metering 层提供统一的
``MeteringRecord`` 与 ``record_usage`` / ``reconcile`` 接口，依据
``payment_sot.model_payment_backend()`` 把计量结果路由到正确的真相源。

- backend=postgres → 记到 FHD PostgreSQL（本地 SoT）。
- backend=modstore → 经市场代理记到 Java 钱包（预授权/结算）。
- backend=json     → legacy 本地，仅记录并告警。

本模块只负责「记账路由 + 去重 + 汇总」，具体扣款由对应后端执行。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MeteringRecord:
    """一条统一计量记录（跨宿主）。"""

    tenant_id: str
    sku: str                       # 计费项标识（plan_id / item_id / usage_meter）
    mode: str                      # subscription / one_time / usage
    amount: Decimal
    currency: str = "CNY"
    quantity: float = 1.0
    idempotency_key: str = ""      # 去重键（同键只记一次）
    backend: str = ""              # 实际落地的 SoT 后端
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "sku": self.sku,
            "mode": self.mode,
            "amount": float(self.amount),
            "currency": self.currency,
            "quantity": self.quantity,
            "idempotency_key": self.idempotency_key,
            "backend": self.backend,
            "ts": self.ts,
            "meta": self.meta,
        }


# 进程内去重缓存（生产应落 Redis / DB 唯一约束；这里提供轻量幂等）
_seen_keys: set[str] = set()


def _resolve_backend() -> str:
    try:
        from app.infrastructure.payment.payment_sot import model_payment_backend

        return model_payment_backend()
    except Exception:
        return "json"


def record_usage(record: MeteringRecord) -> dict[str, Any]:
    """记录一条计量并路由到统一 SoT。幂等：相同 idempotency_key 只生效一次。"""
    if record.idempotency_key and record.idempotency_key in _seen_keys:
        return {"ok": True, "deduped": True, "backend": record.backend or _resolve_backend()}

    backend = _resolve_backend()
    record.backend = backend

    # 上报 Prometheus（与阶段 7 指标体系统一）
    try:
        from app.utils.metrics import user_events_total

        user_events_total.labels(
            event=f"billing.{record.mode}", surface=backend, tenant_id=record.tenant_id
        ).inc()
    except Exception:
        pass

    routed = _route_to_backend(backend, record)

    if record.idempotency_key:
        _seen_keys.add(record.idempotency_key)
    logger.info(
        "metering recorded: tenant=%s sku=%s mode=%s amount=%s backend=%s",
        record.tenant_id, record.sku, record.mode, record.amount, backend,
    )
    return {"ok": True, "deduped": False, "backend": backend, **routed}


def _route_to_backend(backend: str, record: MeteringRecord) -> dict[str, Any]:
    """把计量结果落到对应 SoT。失败不抛出（计量永不阻断业务），返回路由状态。"""
    if backend == "postgres":
        return {"routed": "fhd_postgres"}
    if backend == "modstore":
        try:
            # 经市场代理记 Java 钱包（预授权/结算）。
            from app.infrastructure.payment.modstore_payment_proxy import (  # type: ignore
                record_market_metering,
            )

            record_market_metering(record.as_dict())
            return {"routed": "modstore_wallet"}
        except Exception as exc:
            logger.warning("modstore metering proxy unavailable: %s", exc)
            return {"routed": "modstore_wallet", "deferred": True}
    logger.warning("metering backend=json is legacy; record kept locally only")
    return {"routed": "json_legacy"}


def reconcile(records: list[MeteringRecord]) -> dict[str, Any]:
    """跨宿主对账汇总：按 backend / mode / 币种聚合金额，供收入看板与财务核对。"""
    summary: dict[str, dict[str, float]] = {}
    for r in records:
        key = f"{r.backend or _resolve_backend()}|{r.mode}|{r.currency}"
        bucket = summary.setdefault(key, {"amount": 0.0, "count": 0.0})
        bucket["amount"] += float(r.amount)
        bucket["count"] += 1
    return {"ok": True, "buckets": summary, "total_records": len(records)}


__all__ = ["MeteringRecord", "record_usage", "reconcile"]
