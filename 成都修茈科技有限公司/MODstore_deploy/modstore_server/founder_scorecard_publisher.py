"""Scheduled publisher for the public founder-autonomy scorecard.

The admin cockpit remains session-gated for humans.  This worker uses two
independent credentials for unattended refreshes:

* a short-lived MODstore admin bearer for reading live evidence; and
* the shared autonomy webhook token for authorising the FHD publish action.

No credential or internal evidence payload is written to the public file.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _fhd_base_url() -> str:
    return (
        str(
            os.environ.get("MODSTORE_FOUNDER_SCORECARD_FHD_BASE_URL")
            or os.environ.get("MODSTORE_FHD_LOCAL_BASE_URL")
            or "http://127.0.0.1:5100"
        )
        .strip()
        .rstrip("/")
    )


def _autonomy_token() -> str:
    return str(
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()


def _timeout_seconds() -> float:
    try:
        return max(
            15.0,
            min(
                180.0,
                float(os.environ.get("MODSTORE_FOUNDER_SCORECARD_TIMEOUT_SECONDS", "90")),
            ),
        )
    except ValueError:
        return 90.0


def publish_founder_scorecard() -> dict[str, Any]:
    """Refresh the seven dimensions and atomically publish the public subset.

    Failures raise so ``scheduler_runtime`` records a failed job instead of
    treating a login error or partial publication as a successful heartbeat.
    """

    from modstore_server.daily_digest_surface_audit import _login_surface_audit_sync

    auth = _login_surface_audit_sync(label="founder-scorecard")
    market_bearer = str(auth.get("access_token") or "").strip()
    autonomy_token = _autonomy_token()
    if not market_bearer:
        raise RuntimeError("founder scorecard refresh has no market admin bearer")
    if not autonomy_token:
        raise RuntimeError("founder scorecard refresh has no autonomy webhook token")

    request = urllib.request.Request(
        f"{_fhd_base_url()}/api/xcmax/ops/founder-autonomy/refresh-internal",
        data=b"{}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {market_bearer}",
            "Content-Type": "application/json",
            "User-Agent": "MODstore-founder-scorecard/1.0",
            "X-Autonomy-Token": autonomy_token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    if not isinstance(payload, dict) or not payload.get("success"):
        raise RuntimeError("founder scorecard refresh endpoint rejected publication")
    snapshot = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    dimensions = snapshot.get("dimensions")
    publication = payload.get("publication") if isinstance(payload.get("publication"), dict) else {}
    if not isinstance(dimensions, list) or len(dimensions) != 7:
        raise RuntimeError("founder scorecard refresh returned incomplete dimensions")
    if not publication.get("ok"):
        raise RuntimeError("founder scorecard public projection was not fully published")

    return {
        "ok": True,
        "generated_at": str(snapshot.get("generated_at") or ""),
        "overall_progress": int(snapshot.get("overall_progress") or 0),
        "dimension_count": len(dimensions),
        "published_target_count": len(publication.get("written") or []),
    }


__all__ = ["publish_founder_scorecard"]
