"""Authenticated same-origin assets for verified, independently installed Mods."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.mod_sdk.runtime_frontend import runtime_asset, runtime_metadata

router = APIRouter()


@router.get("/runtime/{mod_id}")
def runtime_frontend(request: Request, mod_id: str):
    return {"success": True, "data": runtime_metadata(request, mod_id)}


@router.get("/runtime/{mod_id}/assets/{revision}/{relative_path:path}")
def runtime_frontend_asset(request: Request, mod_id: str, revision: str, relative_path: str):
    content, media_type = runtime_asset(request, mod_id, revision, relative_path)
    return Response(
        content,
        media_type=media_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
