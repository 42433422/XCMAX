"""支付后端健康探测（PAYMENT_BACKEND=java 切换与运维验收）。"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter

from modstore_server.application.payment_gateway import PaymentGatewayService
from modstore_server.payment_orders import is_local_source_of_truth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


def compute_payment_health() -> dict[str, Any]:
    gateway = PaymentGatewayService()
    backend = gateway.backend
    java_url = gateway.target_base_url()
    out: dict[str, Any] = {
        "payment_backend": backend,
        "java_payment_service_url": java_url,
        "java_proxy_enabled": backend == "java",
        "local_json_sot_writable": is_local_source_of_truth(),
        "java_payment_reachable": None,
        "java_actuator_status": None,
        "ready_for_java_cutover": False,
    }
    health_url = f"{java_url}/actuator/health"
    try:
        resp = httpx.get(
            health_url,
            timeout=httpx.Timeout(
                gateway.connect_timeout_seconds,
                read=gateway.read_timeout_seconds,
            ),
        )
        out["java_payment_reachable"] = resp.status_code < 500
        ct = (resp.headers.get("content-type") or "").lower()
        body: dict[str, Any] | None = None
        if "json" in ct or resp.status_code == 200:
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    body = parsed
            except Exception:
                body = None
        if body:
            out["java_actuator_status"] = body.get("status")
        else:
            out["java_actuator_status"] = "unknown"
    except Exception as exc:
        logger.debug("java payment health probe failed", exc_info=True)
        out["java_payment_reachable"] = False
        out["java_probe_error"] = str(exc)[:300]

    java_up = bool(
        out.get("java_payment_reachable")
        and str(out.get("java_actuator_status") or "").upper() == "UP"
    )
    out["java_service_healthy"] = java_up
    if backend == "java":
        out["ready_for_java_cutover"] = java_up and not out.get("local_json_sot_writable")
    else:
        out["ready_for_java_cutover"] = java_up
        out["note"] = (
            "Java is healthy; set PAYMENT_BACKEND=java and restart api to complete cutover"
            if java_up
            else "Start payment-service before flipping PAYMENT_BACKEND"
        )
    return out


@router.get("/payment", summary="支付后端与 Java 服务探活")
def api_payment_health() -> dict[str, Any]:
    data = compute_payment_health()
    status = "ok"
    if data.get("payment_backend") == "java":
        if not data.get("java_payment_reachable"):
            status = "degraded"
        elif not data.get("ready_for_java_cutover"):
            status = "degraded"
    return {"status": status, **data}
