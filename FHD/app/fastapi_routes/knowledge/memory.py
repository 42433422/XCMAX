"""Persy memory review, audit responses and knowledge-recall composition."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.application.knowledge.protocols import AccessResolver, MemoryResponse
from app.fastapi_routes.knowledge.schemas import PersyMemoryMutationRequest, PersyMemoryQueryRequest
from app.utils.operational_errors import RECOVERABLE_ERRORS


def dataset_error(dataset_id: str, persy_dataset_id: str) -> JSONResponse | None:
    if str(dataset_id or "").strip() == persy_dataset_id:
        return None
    return JSONResponse(
        {
            "success": False,
            "message": "Persy memory is only available for the Persy knowledge dataset",
            "error_code": "persy_dataset_required",
        },
        status_code=404,
    )


def memory_response(
    payload: dict[str, Any],
    *,
    request: Request,
    action: str,
    access_resolver: AccessResolver,
    logger: logging.Logger,
) -> JSONResponse:
    success = bool(payload.get("success"))
    code = str(payload.get("error_code") or "")
    status_code = 200 if success else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    elif code == "persy_memory_not_found":
        status_code = 404
    try:
        from app.utils.logging import audit_logger

        access = access_resolver(request)
        audit_logger.audit_log(
            f"persy_memory_{action}",
            getattr(access, "actor_id", "") if access is not None else "",
            str(getattr(getattr(request, "client", None), "host", "") or ""),
            {
                "success": success,
                "memory_id": str(
                    (payload.get("memory") or {}).get("memory_id")
                    if isinstance(payload.get("memory"), dict)
                    else ""
                ),
                "error_code": code,
            },
            success=success,
        )
    except RECOVERABLE_ERRORS:
        logger.debug("Persy memory audit unavailable", exc_info=True)
    return JSONResponse(payload, status_code=status_code)


class MemoryReview:
    def __init__(
        self,
        *,
        service: Callable[[], PersyMemoryApplicationService],
        access: AccessResolver,
        dataset_error: Callable[[str], JSONResponse | None],
        response: MemoryResponse,
        dataset_id: str,
    ) -> None:
        self._service = service
        self._access = access
        self._dataset_error = dataset_error
        self._response = response
        self._dataset_id = dataset_id

    def list_memories(
        self,
        dataset_id: str,
        request: Request,
        status: str = "",
        memory_type: str = "",
        limit: int = 200,
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        payload = self._service().list_memories(
            access_context=self._access(request),
            status=status,
            memory_type=memory_type,
            limit=limit,
        )
        code = str(payload.get("error_code") or "")
        status_code = 200 if payload.get("success") else 400
        if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
            status_code = 403
        return JSONResponse(payload, status_code=status_code)

    def query(
        self, dataset_id: str, req: PersyMemoryQueryRequest, request: Request
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        payload = self._service().query(
            access_context=self._access(request),
            query=req.query,
            top_k=req.top_k,
            reinforce=req.reinforce,
        )
        code = str(payload.get("error_code") or "")
        status_code = 200 if payload.get("success") else 400
        if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
            status_code = 403
        return JSONResponse(payload, status_code=status_code)

    def confirm(
        self, dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        correction: dict[str, Any] = {
            key: getattr(req, key)
            for key in ("key", "value", "memory_type", "confidence")
            if key in req.model_fields_set
        }
        payload = self._service().mutate(
            access_context=self._access(request),
            memory_id=memory_id,
            action="confirm",
            patch=correction,
            reason=req.reason,
        )
        return self._response(payload, request=request, action="confirm")

    def reject(
        self, dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        payload = self._service().mutate(
            access_context=self._access(request),
            memory_id=memory_id,
            action="reject",
            reason=req.reason,
        )
        return self._response(payload, request=request, action="reject")

    def correct(
        self, dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        patch: dict[str, Any] = {
            key: getattr(req, key) for key in ("key", "value") if key in req.model_fields_set
        }
        payload = self._service().mutate(
            access_context=self._access(request),
            memory_id=memory_id,
            action="correct",
            patch=patch,
            reason=req.reason,
        )
        return self._response(payload, request=request, action="correct")

    def delete(
        self, dataset_id: str, memory_id: str, request: Request, reason: str = ""
    ) -> JSONResponse:
        unsupported = self._dataset_error(dataset_id)
        if unsupported is not None:
            return unsupported
        payload = self._service().mutate(
            access_context=self._access(request),
            memory_id=memory_id,
            action="delete",
            reason=reason,
        )
        return self._response(payload, request=request, action="delete")

    def merge_recall(
        self, payload: dict[str, Any], *, request: Request, params: dict[str, Any]
    ) -> dict[str, Any]:
        if str(params.get("dataset_id") or "") != self._dataset_id or not payload.get("success"):
            return payload
        query_text = str(params.get("query") or "").strip()
        if not query_text:
            return payload
        memory_result = self._service().query(
            access_context=self._access(request),
            query=query_text,
            top_k=max(1, min(int(params.get("top_k") or 5), 20)),
            reinforce=True,
        )
        result = dict(payload)
        result["persy_memory"] = {
            "available": bool(memory_result.get("success")),
            "count": len(memory_result.get("chunks") or []),
            "retriever": str(memory_result.get("retriever") or ""),
        }
        if not memory_result.get("success"):
            result["persy_memory"]["error_code"] = str(memory_result.get("error_code") or "")
            return result
        knowledge_chunks = [
            dict(chunk) for chunk in payload.get("chunks", []) if isinstance(chunk, dict)
        ]
        memory_chunks = [
            dict(chunk) for chunk in memory_result.get("chunks", []) if isinstance(chunk, dict)
        ]
        seen: set[str] = set()
        merged_chunks: list[dict[str, Any]] = []
        for chunk in sorted(
            [*memory_chunks, *knowledge_chunks],
            key=lambda item: float(item.get("score") or 0.0),
            reverse=True,
        ):
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            if not isinstance(metadata, dict):
                metadata = {}
            fingerprint = str(
                metadata.get("memory_id")
                or metadata.get("document_id")
                or f"{chunk.get('source')}:{chunk.get('chunk_index')}:{chunk.get('text')}"
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            merged_chunks.append(chunk)
        result["chunks"] = merged_chunks[: max(2, min(int(params.get("top_k") or 5) * 2, 40))]
        citations = [
            dict(citation)
            for citation in payload.get("citations", [])
            if isinstance(citation, dict)
        ]
        for chunk in memory_chunks:
            memory_metadata = (
                chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            )
            if not isinstance(memory_metadata, dict):
                memory_metadata = {}
            citations.append(
                {
                    "index": len(citations) + 1,
                    "source": "对话记忆",
                    "text": str(chunk.get("text") or ""),
                    "score": chunk.get("score"),
                    "memory_id": memory_metadata.get("memory_id"),
                }
            )
        result["citations"] = citations
        if memory_chunks and params.get("include_answer", True):
            memory_summary = "；".join(
                str(chunk.get("text") or "").strip()[:180]
                for chunk in memory_chunks[:3]
                if str(chunk.get("text") or "").strip()
            )
            knowledge_answer = str(payload.get("answer") or "").strip()
            memory_answer = f"已确认的长期记忆：{memory_summary}。" if memory_summary else ""
            result["answer"] = "\n\n".join(
                part for part in (memory_answer, knowledge_answer) if part
            )
        return result
