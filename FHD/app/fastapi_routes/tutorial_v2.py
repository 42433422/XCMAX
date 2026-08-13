"""Public API for Tutorial V2 real-business practice."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook  # type: ignore[import-untyped]
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.tutorial_v2.scope import COOKIE_MAX_AGE_SECONDS, TUTORIAL_COOKIE
from app.application.tutorial_v2.service import TutorialServiceError, TutorialV2Service
from app.db.session import get_db_dependency
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.schemas.tutorial_v2 import TutorialCourseDTO, TutorialRunDTO

router = APIRouter(prefix="/api/tutorial/v2", tags=["tutorial-v2"])
service = TutorialV2Service()
logger = logging.getLogger(__name__)


class TutorialRunCreate(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)


class TutorialVerifyRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


def _error(exc: TutorialServiceError) -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "error": {"code": exc.code, "hint": exc.hint},
        },
        status_code=exc.status_code,
    )


def _unexpected(operation: str) -> JSONResponse:
    logger.warning("tutorial v2 operation failed operation=%s", operation)
    return JSONResponse(
        {
            "success": False,
            "error": {
                "code": "tutorial_service_unavailable",
                "hint": "教程服务暂时不可用，请保存当前工作后重试。",
            },
        },
        status_code=503,
    )


def _set_cookie(response: JSONResponse, request: Request, run_id: str) -> None:
    response.set_cookie(
        TUTORIAL_COOKIE,
        run_id,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


@router.get("/courses")
def courses(
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        data = [
            TutorialCourseDTO.model_validate(item).model_dump(mode="json")
            for item in service.list_courses(db, user)
        ]
        return {"success": True, "data": data}
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001 - public boundary must never expose raw backend text
        return _unexpected("courses")


@router.post("/runs")
def create_or_resume_run(
    body: TutorialRunCreate,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run = service.start_run(db, user, body.course_id)
        return {
            "success": True,
            "data": TutorialRunDTO.model_validate(service.run_dto(run)).model_dump(mode="json"),
        }
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("start_run")


@router.get("/runs/current")
def current_run(
    request: Request,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run = service.current_run(
            db,
            user,
            preferred_run_id=request.cookies.get(TUTORIAL_COOKIE),
        )
        return {"success": True, "data": service.run_dto(run) if run else None}
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("current_run")


@router.post("/runs/{run_id}/enter")
def enter_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run = service.enter_run(db, user, run_id)
        response = JSONResponse({"success": True, "data": service.run_dto(run)})
        _set_cookie(response, request, run.id)
        return response
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("enter_run")


@router.post("/runs/{run_id}/leave")
def leave_run(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run = service.leave_run(db, user, run_id)
        response = JSONResponse({"success": True, "data": service.run_dto(run)})
        response.delete_cookie(TUTORIAL_COOKIE, path="/")
        return response
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("leave_run")


@router.post("/runs/{run_id}/steps/{step_id}/verify")
def verify_step(
    run_id: str,
    step_id: str,
    request: Request,
    body: TutorialVerifyRequest = Body(default_factory=TutorialVerifyRequest),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run, evidence = service.verify_step(
            db,
            user,
            run_id,
            step_id,
            cookie_run_id=request.cookies.get(TUTORIAL_COOKIE),
            context=body.context,
        )
        response = JSONResponse(
            {
                "success": evidence.status == "passed",
                "data": {
                    "run": service.run_dto(run),
                    "evidence": {
                        "step_id": evidence.step_id,
                        "status": evidence.status,
                        "result_code": evidence.result_code,
                        "entity_refs": service._evidence_dto(evidence)["entity_refs"],
                        "counts": service._evidence_dto(evidence)["counts"],
                        "attempt_count": evidence.attempt_count,
                        "verified_at": evidence.verified_at.isoformat()
                        if evidence.verified_at
                        else None,
                    },
                    "hint": service.safe_hint(evidence.result_code),
                },
            },
            status_code=200,
        )
        return response
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("verify_step")


@router.post("/runs/{run_id}/reset")
def reset_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        run = service.reset_run(db, user, run_id)
        response = JSONResponse({"success": True, "data": service.run_dto(run)})
        _set_cookie(response, request, run.id)
        return response
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("reset_run")


@router.get("/reports")
def reports(
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(get_logged_in_user),
):
    try:
        return {"success": True, "data": service.reports(db, user)}
    except TutorialServiceError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return _unexpected("reports")


@router.get("/assets/business-import.xlsx")
def tutorial_excel(request: Request, _user: Any = Depends(get_logged_in_user)):
    """Generate the built-in teaching workbook without writing repository files."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "教学客户产品"
    sheet.append(["客户名称", "产品名称", "产品编码", "单价", "库存", "错误示例"])
    workspace_token = str(getattr(request.state, "tutorial_workspace_id", "practice") or "practice")
    workspace_token = workspace_token.replace("-", "")[:10]
    sheet.append(["教学客户C", "教学产品C", f"TUTORIAL-{workspace_token}-C", 88, 12, ""])
    sheet.append(
        [
            "教学客户D",
            "",
            f"TUTORIAL-{workspace_token}-D",
            "错误单价",
            5,
            "用于认识错误行",
        ]
    )
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="xcagi-tutorial-business-import.xlsx"'
        },
    )


__all__ = ["router"]
