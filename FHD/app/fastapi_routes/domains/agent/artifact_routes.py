"""Authenticated downloads for verified Agent artifacts."""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse, Response

from app.application.agent_orchestrator import AgentOrchestrator
from app.fastapi_routes.domains.agent.route_support import owned_run as _owned_run
from app.fastapi_routes.domains.agent.task_routes import router
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal


@router.get("/api/agent/runs/{run_id}/artifacts/{artifact_id}", response_model=None)
def download_agent_artifact(
    run_id: str,
    artifact_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> Response:
    from urllib.parse import quote

    from app.application.agent_orchestrator.artifact_files import read_verified_spreadsheet

    run, error = _owned_run(AgentOrchestrator(), run_id, principal)
    if error is not None:
        return error
    artifact = (
        next((item for item in run.artifacts if item.artifact_id == artifact_id), None)
        if run
        else None
    )
    if artifact is None or artifact.artifact_type != "file":
        return JSONResponse({"success": False, "message": "文件不存在"}, status_code=404)
    try:
        content = read_verified_spreadsheet(run_id, artifact.to_dict())
    except (OSError, ValueError, KeyError):
        return JSONResponse(
            {"success": False, "message": "文件不可用，请重新导出"}, status_code=410
        )
    return Response(
        content=content,
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact.name, safe='')}",
            "Cache-Control": "private, no-store",
        },
    )
