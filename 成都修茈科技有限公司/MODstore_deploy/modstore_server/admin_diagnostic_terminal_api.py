"""Administrator API for the shared read-only diagnostic terminal."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.diagnostic_terminal import (
    DiagnosticTerminalError,
    command_catalog,
    execute_diagnostic_command,
)
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/admin/diagnostic-terminal", tags=["admin-diagnostics"])


class DiagnosticCommandBody(BaseModel):
    command: str = Field(default="doctor", min_length=1, max_length=512)


def _runtime_routes(request: Request) -> list[dict[str, Any]]:
    # The app uses lazy routers, so the top-level route table is not enough.
    # Reuse the same recursive flattener as startup conflict detection.
    from modstore_server.api.app_factory import _iter_route_method_signatures

    grouped: dict[str, set[str]] = {}
    for path, method in _iter_route_method_signatures(request.app.routes):
        grouped.setdefault(str(path), set()).add(str(method))
    return [
        {"path": path, "name": "", "methods": sorted(methods)}
        for path, methods in sorted(grouped.items())
    ]


@router.get("/commands")
def list_diagnostic_commands(_admin: User = Depends(require_admin)):
    return {"ok": True, "read_only": True, "items": command_catalog()}


@router.post("/execute")
def execute_admin_diagnostic_command(
    body: DiagnosticCommandBody,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        return execute_diagnostic_command(
            db,
            body.command,
            route_catalog=_runtime_routes(request),
        )
    except DiagnosticTerminalError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(
            503,
            f"诊断数据源暂不可用：{type(exc).__name__}",
        ) from exc


__all__ = ["DiagnosticCommandBody", "router"]
