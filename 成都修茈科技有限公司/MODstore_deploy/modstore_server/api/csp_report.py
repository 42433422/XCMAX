"""CSP violation reporting (Report-Only policy)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response

from modstore_server.metrics import observe_csp_violation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["csp"])


@router.post("/api/csp-report")
async def csp_report(request: Request) -> Response:
    """Browser ``report-uri`` / ``report-to`` payloads (JSON array or object)."""
    raw = await request.body()
    observe_csp_violation()
    if raw:
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(data, list) and data:
                data = data[0]
            if isinstance(data, dict):
                logger.info(
                    "csp-report: %s",
                    {
                        k: data.get(k)
                        for k in ("document-uri", "violated-directive", "blocked-uri")
                        if k in data
                    },
                )
        except (json.JSONDecodeError, UnicodeError):
            logger.debug("csp-report: non-json body len=%s", len(raw))
    return Response(status_code=204)
