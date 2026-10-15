"""Independent SUNBIRD conversion extension; no private host build required."""

import sys
from pathlib import Path

from fastapi import APIRouter, Depends

from app.mod_sdk.owner_workspace import require_owner_workspace

MOD_ID = "sunbird-attendance-custom"


def _runtime():
    backend = str(Path(__file__).resolve().parent)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from sunbird_attendance import api

    return api


def register_fastapi_routes(app, mod_id: str):
    if mod_id != MOD_ID:
        raise ValueError("custom Mod identity mismatch")
    api = _runtime()
    router = APIRouter(dependencies=[Depends(require_owner_workspace), Depends(api.require_access)])
    api.register(router)
    app.include_router(router, prefix=f"/api/mod/{MOD_ID}")
    app.include_router(router, prefix=f"/api/mods/{MOD_ID}")


def mod_init():
    _runtime()


def verify_delivery(request):
    api = _runtime()
    api.require_access(request)
    from sunbird_attendance.verification import verify_conversion

    return verify_conversion(request)
