"""六线统一 webhook：GitHub CI / Grafana 等 → event_type → router。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from app.application.six_line_event_app_service import get_six_line_event_app_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/webhooks", tags=["six-line-webhook"])


def _verify_secret(request: Request, raw: bytes, signature: str | None) -> bool:
    secret = (
        os.environ.get("SIX_LINE_WEBHOOK_SECRET")
        or os.environ.get("XCAGI_TELEMETRY_INGEST_SECRET")
        or ""
    ).strip()
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    sig = signature.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, sig)


def _normalize_github(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("workflow_run"):
        run = payload["workflow_run"]
        if str(run.get("conclusion") or "") == "failure":
            return {
                "event_type": "ci.failed",
                "step_id": "P3",
                "status": "anomaly",
                "payload": {"source": "github", "run_id": run.get("id")},
            }
    return None


def _normalize_grafana(payload: dict[str, Any]) -> dict[str, Any] | None:
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        return {
            "event_type": "security.alert",
            "step_id": "R4",
            "status": "anomaly",
            "payload": {"source": "grafana", "alerts": len(alerts)},
        }
    if payload.get("state") == "alerting":
        return {
            "event_type": "security.alert",
            "step_id": "R4",
            "status": "anomaly",
            "payload": {"source": "grafana"},
        }
    return None


def _normalize_body(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("event_type") and body.get("step_id"):
        return body
    gh = _normalize_github(body)
    if gh:
        return gh
    gr = _normalize_grafana(body)
    if gr:
        return gr
    return {
        "event_type": str(body.get("event_type") or "ops.intake.task.queued"),
        "step_id": str(body.get("step_id") or "O7"),
        "status": str(body.get("status") or "progress"),
        "payload": body.get("payload") if isinstance(body.get("payload"), dict) else body,
    }


@router.post("/six-line")
async def six_line_webhook(
    request: Request,
    body: dict[str, Any] = Body(...),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_six_line_signature: str | None = Header(default=None, alias="X-Six-Line-Signature"),
):
    raw = await request.body()
    sig = x_six_line_signature or x_hub_signature_256
    if not _verify_secret(request, raw, sig):
        return JSONResponse({"success": False, "message": "invalid signature"}, status_code=401)
    normalized = _normalize_body(body)
    data = get_six_line_event_app_service().dispatch(normalized)
    return JSONResponse({"success": True, "data": data})
