"""制作线 P10：将 FHD 生产遥测信号 POST 至 MODstore internal telemetry API。"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _market_base() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "").rstrip("/")


def _ingest_secret() -> str:
    return (os.environ.get("XCAGI_TELEMETRY_INGEST_SECRET") or "").strip()


def emit_telemetry_signal(
    signal_type: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """向 MODstore 投递遥测信号；未配置 base URL 时仅写日志。"""
    base = _market_base()
    if not base:
        logger.debug("telemetry bridge skipped: XCAGI_MARKET_BASE_URL unset")
        return {"ok": True, "skipped": True, "reason": "no_market_base"}

    secret = _ingest_secret()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Telemetry-Secret"] = secret

    body = {
        "signal_type": signal_type,
        "payload": payload or {},
        "source": "fhd_prod",
    }
    try:
        import httpx

        resp = httpx.post(
            f"{base}/api/internal/telemetry/ingest",
            json=body,
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code >= 400:
            logger.warning("telemetry ingest HTTP %s: %s", resp.status_code, resp.text[:200])
            return {"ok": False, "status_code": resp.status_code}
        return resp.json() if resp.content else {"ok": True}
    except Exception:
        logger.exception("telemetry ingest failed")
        return {"ok": False, "error": "request_failed"}


def maybe_emit_coverage_drop(current_pct: float, threshold: float = 40.0) -> dict[str, Any]:
    if current_pct >= threshold:
        return {"ok": True, "skipped": True}
    return emit_telemetry_signal(
        "coverage_drop",
        {
            "description": f"FHD 全量 app 覆盖率 {current_pct:.1f}% 低于目标 {threshold}%",
            "current_pct": current_pct,
            "threshold": threshold,
        },
    )
