"""Session-authenticated, fixed-path management proxy for Mac control."""

from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request

router = APIRouter()


async def proxy(request: Request, method: str, path: str, body: dict | None = None):
    from app.fastapi_routes.xcmax_admin import _market_admin_proxy

    return await _market_admin_proxy(
        request, method, "/api/admin/mac-control/" + path, json_body=body
    )


@router.get("/admin/mac-control/fleet")
async def fleet(request: Request):
    return await proxy(request, "GET", "fleet")


@router.get("/admin/mac-control/tasks")
async def tasks(request: Request):
    return await proxy(request, "GET", "tasks")


@router.get("/admin/mac-control/tasks/{task_id}")
async def detail(request: Request, task_id: str, after: int = Query(0, ge=0)):
    from urllib.parse import quote

    return await proxy(
        request, "GET", "tasks/" + quote(task_id, safe="") + "?" + urlencode({"after": after})
    )


@router.post("/admin/mac-control/tasks/{task_id}/cancel")
async def cancel(request: Request, task_id: str):
    from urllib.parse import quote

    return await proxy(request, "POST", "tasks/" + quote(task_id, safe="") + "/cancel", {})


@router.get("/admin/mac-control/facts")
async def facts(request: Request, customer_id: int | None = Query(None, gt=0)):
    suffix = "?" + urlencode({"customer_id": customer_id}) if customer_id else ""
    return await proxy(request, "GET", "facts" + suffix)
