"""Authenticated, tenant/user-owned label generation and confirmed printing."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.application.label_job_service import LabelJobError, LabelJobService
from app.fastapi_routes.print_agent_helpers import run_print_agent
from app.infrastructure.auth.dependencies import get_logged_in_user

router = APIRouter(prefix="/label-jobs", tags=["print-label-jobs"])


class GenerateLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: Annotated[int, Field(strict=True, gt=0)]
    template_id: Annotated[str, Field(min_length=1, max_length=80)]
    copies: Annotated[int, Field(strict=True, ge=1, le=100)]
    paper_width_mm: Annotated[float, Field(ge=10, le=500, allow_inf_nan=False)]
    paper_height_mm: Annotated[float, Field(ge=10, le=500, allow_inf_nan=False)]


class ConfirmLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_token: Annotated[str, Field(min_length=20, max_length=100)]


def _owner(user: Any = Depends(get_logged_in_user)) -> tuple[int, int]:
    tid, uid = getattr(user, "tenant_id", None), getattr(user, "id", None)
    if not isinstance(tid, int) or not isinstance(uid, int) or tid < 1 or uid < 1:
        raise HTTPException(403, "登录账号缺少租户归属，无法生成或访问标签")
    return tid, uid


def _service() -> LabelJobService:
    return LabelJobService()


def _call(function, *args):
    try:
        return function(*args)
    except LabelJobError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("")
def generate_label(body: GenerateLabel, owner=Depends(_owner)):
    return {"success": True, "job": _call(_service().generate, owner, body.model_dump())}


@router.get("/products")
def label_products(
    keyword: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1, le=1000000),
    per_page: int = Query(default=50, ge=1, le=100),
    owner=Depends(_owner),
):
    return _call(_service().products, owner, keyword, page, per_page)


@router.get("/{job_id}")
def get_label_job(job_id: str, owner=Depends(_owner)):
    return {"success": True, "job": _call(_service().get, owner, job_id)}


@router.get("/{job_id}/file")
def download_label(job_id: str, owner=Depends(_owner)):
    path = _call(_service().file, owner, job_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"labels-{job_id}.pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{job_id}/confirmation")
def confirm_label(job_id: str, owner=Depends(_owner)):
    from app.application.facades.print_facade import printer_service

    return {
        "success": True,
        **_call(_service().confirmation, owner, job_id, printer_service.get_label_printer()),
    }


@router.post("/{job_id}/submit")
def submit_label(job_id: str, body: ConfirmLabel, request: Request, owner=Depends(_owner)):
    service = _service()
    job = _call(service.get, owner, job_id)
    receipt, status = run_print_agent(
        request=request,
        action="submit_label_job",
        params={"job_id": job_id, "confirm_token": body.confirm_token},
        route_path=f"/api/print/label-jobs/{job_id}/submit",
    )
    if receipt.get("run_id"):
        job = _call(service.bind_execution, owner, job_id, receipt)
    return JSONResponse({**receipt, "job": job}, status_code=status)
