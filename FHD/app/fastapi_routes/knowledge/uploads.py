"""Own uploaded document streams and staged files until the Agent accepts them."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.knowledge.ports import DatasetAction


def _accepted_input(response: JSONResponse) -> bool:
    if response.status_code >= 400:
        return False
    if response.status_code == 202:
        return True
    try:
        payload = json.loads(bytes(response.body))
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and (
        bool(payload.get("success"))
        or payload.get("agent_status") in {"waiting_user", "running", "blocked"}
    )


class DocumentUpload:
    """The Agent owns accepted inputs; every other path releases this upload."""

    def __init__(
        self,
        *,
        dispatch: DatasetAction,
        directory: Callable[[], str | Path],
        extensions: frozenset[str],
        max_bytes: int,
        logger: logging.Logger,
    ) -> None:
        self._dispatch = dispatch
        self._directory = directory
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
        saved_path: Path | None = None
        created = False
        retained = False
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

            base = (Path(self._directory()).resolve() / "knowledge").resolve()
            segment = re.sub("[^A-Za-z0-9._-]+", "_", str(dataset_id or "default"))[:100]
            if segment in {"", ".", ".."}:
                segment = "default"
            upload_dir = (base / segment).resolve()
            if not upload_dir.is_relative_to(base):
                return JSONResponse(
                    {"success": False, "message": "资料上传目录无效"}, status_code=400
                )
            upload_dir.mkdir(parents=True, exist_ok=True)
            saved_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
            size = 0
            try:
                # Never overwrite or later delete a pre-existing file on collision.
                with saved_path.open("xb") as target:
                    created = True
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ValueError("资料文件不能超过 25 MB")
                        target.write(chunk)
            except (OSError, ValueError) as exc:
                return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
            try:
                await file.close()
            finally:
                input_closed = True
            response = self._dispatch(
                request=request,
                action="ingest_document",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/upload",
                params={
                    "dataset_id": dataset_id,
                    "source": source_label,
                    "file_path": str(saved_path),
                    "text": "",
                    "document_id": "",
                    "chunk_strategy": chunk_strategy
                    if chunk_strategy in {"semantic", "fixed"}
                    else "semantic",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "metadata": {
                        "original_file_name": original_name,
                        "upload_size_bytes": size,
                        "entrypoint": "persy_knowledge_upload",
                    },
                    "tenant_id": tenant_id,
                    "version": version,
                    "version_label": version_label,
                },
            )
            retained = _accepted_input(response)
            return response
        finally:
            try:
                if not input_closed:
                    await file.close()
            finally:
                if created and saved_path is not None and not retained:
                    try:
                        saved_path.unlink(missing_ok=True)
                    except OSError:
                        self._logger.warning(
                            "Failed to clean rejected Persy upload: %s", saved_path
                        )
