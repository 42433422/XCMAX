"""Authenticated download route for account-owned AI API exports."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["aiopen"])


@router.get("/api/aiopen/artifacts/{artifact_id}")
def aiopen_artifact_download(artifact_id: str):
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.application.agent_orchestrator.task_mod_scope import TaskModScopeError
    from app.application.aiopen.api_artifacts import ApiArtifactError, read_api_export
    from app.application.aiopen.api_execution import ApiExecutionError

    try:
        content, metadata = read_api_export(artifact_id)
    except (ApiArtifactError, ApiExecutionError, TaskModScopeError):
        return JSONResponse(
            {"success": False, "message": "导出文件不存在、已失效或无权访问"}, status_code=404
        )
    return Response(
        content,
        media_type=metadata["mime_type"],
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(metadata["name"], safe=""),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": metadata["sha256"],
        },
    )
