"""Bounded uploads retain an immutable, actor-owned input for canonical retries."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse

from app.application.knowledge.protocols import DatasetAction
from app.fastapi_routes.domains.agent.route_support import request_runtime_context
from app.utils.path_io.upload_helpers import (
    _capability_upload_directory,
    stage_capability_upload,
)


def stage_knowledge_input(
    content: bytes, filename: str, context: dict[str, Any], *, suffixes: frozenset[str]
) -> Path:
    receipt = stage_capability_upload(
        content, filename, context, namespace="knowledge", suffixes=suffixes
    )
    return _capability_upload_directory(context, "knowledge") / receipt["saved_name"]


class DocumentUpload:
    """Immutable inputs may be shared by retries; a failed attempt cannot delete them."""

    def __init__(
        self,
        *,
        dispatch: DatasetAction,
        extensions: frozenset[str],
        max_bytes: int,
        logger: logging.Logger,
    ) -> None:
        self._dispatch = dispatch
        self._extensions = extensions
        self._max_bytes = max_bytes
        self._logger = logger

    async def ingest(
        self,
        dataset_id: str,
        request: Request,
        *,
        file: UploadFile,
        source: str,
        tenant_id: str,
        version: str,
        version_label: str,
        chunk_strategy: str,
    ) -> JSONResponse:
        input_closed = False
        try:
            raw_name = Path(str(file.filename or "document")).name
            suffix = Path(raw_name).suffix.lower()
            original_name = f"{Path(raw_name).stem[: max(1, 240 - len(suffix))]}{suffix}"
            if suffix not in self._extensions:
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"不支持的资料类型: {suffix or '无扩展名'}",
                        "allowed_extensions": sorted(self._extensions),
                    },
                    status_code=400,
                )
            source_label = str(source or original_name).strip() or original_name
            if len(source_label) > 300:
                return JSONResponse(
                    {"success": False, "message": "资料名称不能超过 300 个字符"}, status_code=400
                )
            if any(
                len(str(value or "")) > limit
                for value, limit in ((tenant_id, 160), (version, 80), (version_label, 120))
            ):
                return JSONResponse({"success": False, "message": "上传参数过长"}, status_code=400)

            context = request_runtime_context(request)
            content = bytearray()
            try:
                while chunk := await file.read(1024 * 1024):
                    if len(content) + len(chunk) > self._max_bytes:
                        return JSONResponse(
                            {"success": False, "message": "资料文件不能超过 25 MB"},
                            status_code=400,
                        )
                    content.extend(chunk)
                saved_path = stage_knowledge_input(
                    bytes(content), original_name, context, suffixes=self._extensions
                )
            except (OSError, ValueError):
                self._logger.warning("Knowledge upload staging failed", exc_info=True)
                return JSONResponse(
                    {"success": False, "message": "资料文件暂存或校验失败"}, status_code=400
                )
            try:
                await file.close()
            finally:
                input_closed = True
            return self._dispatch(
                request=request,
                action="ingest_document",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/upload",
                params={
                    "dataset_id": dataset_id,
                    "source": source_label,
                    "file_path": str(saved_path),
                    "text": "",
                    "document_id": "",
                    "chunk_strategy": (
                        chunk_strategy if chunk_strategy in {"semantic", "fixed"} else "semantic"
                    ),
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "metadata": {
                        "original_file_name": original_name,
                        "upload_size_bytes": len(content),
                        "entrypoint": "persy_knowledge_upload",
                    },
                    "tenant_id": tenant_id,
                    "version": version,
                    "version_label": version_label,
                },
            )
        finally:
            if not input_closed:
                await file.close()
