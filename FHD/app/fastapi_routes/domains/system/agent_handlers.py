"""System HTTP views of the shared capability, approval and receipt contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.fastapi_routes.tools_execute import run_tools_execute_agent


async def _stage_template_input(
    request: Request, file: UploadFile, *, namespace: str
) -> tuple[str, str]:
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context
    from app.utils.path_io.upload_helpers import (
        _capability_upload_directory,
        stage_capability_upload,
    )

    # Both the initial upload and every retry use the same live account binding.
    context = request_runtime_context(request)
    filename = Path(str(file.filename or "upload.bin")).name
    try:
        content = await file.read()
        receipt = await run_in_threadpool(
            stage_capability_upload,
            content,
            filename,
            context,
            namespace=namespace,
            suffixes=frozenset({Path(filename).suffix.lower()}),
        )
        path = _capability_upload_directory(context, namespace) / receipt["saved_name"]
        return str(path), filename
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=400, detail="模板文件暂存或校验失败") from exc
    finally:
        await file.close()


async def run_templates_analyze_agent(
    *, request: Request, file: UploadFile, template_name: str, template_scope: str
) -> tuple[dict[str, Any], int]:
    saved_path, _ = await _stage_template_input(request, file, namespace="template-analysis")
    return run_tools_execute_agent(
        request=request,
        body={
            "tool_id": "template_extract",
            "action": "extract",
            "params": {
                "file_path": saved_path,
                "template_name": str(template_name or ""),
                "template_scope": str(template_scope or ""),
            },
        },
        route_path="/api/templates/analyze",
    )


async def run_templates_upload_agent(
    *,
    request: Request,
    file: UploadFile,
    template_name: str,
    template_scope: str,
    source: str,
    route_path: str,
) -> tuple[dict[str, Any], int]:
    saved_path, filename = await _stage_template_input(request, file, namespace="document-template")
    return run_tools_execute_agent(
        request=request,
        body={
            "tool_id": "document_template",
            "action": "upload",
            "params": {
                "file_path": saved_path,
                "filename": filename,
                "template_name": str(template_name or ""),
                "template_scope": str(template_scope or ""),
                "source": str(source or "office_upload"),
            },
        },
        route_path=route_path,
    )


def run_system_maintenance_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> tuple[dict[str, Any], int]:
    return run_tools_execute_agent(
        request=request,
        body={"tool_id": "system_maintenance", "action": action, "params": params},
        route_path=route_path,
    )


def run_document_template_agent(
    *,
    request: Request,
    body: dict[str, Any],
    action: str,
    route_path: str,
) -> tuple[dict[str, Any], int]:
    return run_tools_execute_agent(
        request=request,
        body={"tool_id": "document_template", "action": action, "params": body},
        route_path=route_path,
    )
