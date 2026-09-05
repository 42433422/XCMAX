"""Record a desktop installation as soon as a real market login succeeds."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
from pathlib import Path
from typing import Any

from app.build_identity import build_identity
from app.utils.device_system.device_identity import get_stable_device_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_VALID_INSTALLATION_ID = re.compile(r"^[A-Za-z0-9._:-]{16,64}$")


def desktop_installation_id() -> str:
    """Use Electron's installation identity, falling back to the legacy device ID."""
    path = Path(get_app_data_dir()) / "installation-id"
    try:
        installation_id = path.read_text(encoding="utf-8").strip()
    except OSError:
        installation_id = ""
    if _VALID_INSTALLATION_ID.fullmatch(installation_id):
        return installation_id
    legacy_id = str(get_stable_device_id() or "").strip()
    if _VALID_INSTALLATION_ID.fullmatch(legacy_id):
        return legacy_id
    return hashlib.sha256(legacy_id.encode("utf-8")).hexdigest()[:32]


async def report_desktop_login_delivery_receipt(market_token: str) -> dict[str, Any]:
    """Fail open after login while reporting one idempotent receipt per installation."""
    token = str(market_token or "").strip()
    if not token:
        return {"reported": False, "reason": "missing_market_token"}
    installation_id = desktop_installation_id()
    identity = build_identity()
    version = str(
        os.environ.get("XCAGI_VERSION")
        or os.environ.get("APP_VERSION")
        or identity["product_version"]
    ).strip()
    build_sha = str(
        os.environ.get("XCAGI_BUILD_SHA") or os.environ.get("GIT_SHA") or identity["git_sha"]
    ).strip()
    payload = {
        "installation_id": installation_id,
        "idempotency_key": hashlib.sha256(f"desktop_login:{installation_id}".encode()).hexdigest(),
        "channel": ("staging" if os.environ.get("XCAGI_UPDATE_CHANNEL") == "staging" else "stable"),
        "platform": (platform.system() or platform.platform()).lower()[:32],
        "target_version": version,
        "target_build_sha": build_sha,
        "installed_version": version,
        "installed_build_sha": build_sha,
        "status": "installed",
        "error": "",
        "source": "desktop_login",
    }
    try:
        from app.fastapi_routes.market_account import _proxy_json

        response = await _proxy_json(
            "POST",
            "/api/update-installations/receipts",
            json_body=payload,
            authorization=token,
            return_error_payload=True,
            timeout=10.0,
            retries=2,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop login delivery receipt deferred: %s", exc)
        return {"reported": False, "reason": "market_unreachable"}
    if not isinstance(response, dict) or response.get("__proxy_error__"):
        return {"reported": False, "reason": "market_rejected"}
    return {
        "reported": bool(response.get("ok", True)),
        "duplicate": bool(response.get("duplicate")),
        "source": "desktop_login",
    }
