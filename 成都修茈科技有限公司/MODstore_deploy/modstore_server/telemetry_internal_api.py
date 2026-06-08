"""FHD / 外部系统遥测入口 → telemetry_backlog_loop。"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["internal-telemetry"])


class TelemetryIngestBody(BaseModel):
    signal_type: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="fhd", max_length=64)


def _verify_secret(header: str) -> None:
    expected = (os.environ.get("XCAGI_TELEMETRY_INGEST_SECRET") or "").strip()
    if not expected:
        raise HTTPException(503, "XCAGI_TELEMETRY_INGEST_SECRET not configured")
    if (header or "").strip() != expected:
        raise HTTPException(401, "invalid telemetry ingest secret")


@router.post("/api/internal/telemetry/ingest")
def ingest_telemetry(
    body: TelemetryIngestBody,
    x_telemetry_secret: str = Header("", alias="X-Telemetry-Secret"),
):
    _verify_secret(x_telemetry_secret)
    from modstore_server.telemetry_backlog_loop import ingest_telemetry_signal

    allowed = {
        "user_behavior",
        "error_spike",
        "performance_degradation",
        "feature_request",
        "coverage_drop",
        "market_signal",
    }
    if body.signal_type not in allowed:
        raise HTTPException(400, f"unsupported signal_type: {body.signal_type}")
    out = ingest_telemetry_signal(
        body.signal_type,
        body.payload,
        source=body.source,
    )
    return out


@router.post("/api/internal/telemetry/scan")
def trigger_telemetry_scan(
    x_telemetry_secret: str = Header("", alias="X-Telemetry-Secret"),
):
    _verify_secret(x_telemetry_secret)
    from modstore_server.telemetry_backlog_loop import run_telemetry_scan

    return run_telemetry_scan()
