# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_dataset_rag(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    dataset_id = str(params.get("dataset_id") or "").strip()
    if not dataset_id:
        return {"success": False, "message": f"dataset_rag.{action} 缺少 dataset_id 参数"}
    from app.application.dataset_rag_app_service import (
        DATASET_READ_PERMISSION,
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
        get_dataset_rag_app_service,
    )

    service = get_dataset_rag_app_service()

    def as_bool(value: _facade().Any, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if not cleaned:
                return default
            if cleaned in {"1", "true", "yes", "on"}:
                return True
            if cleaned in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def as_int(value: _facade().Any, default: int) -> int:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def as_dict(value: _facade().Any) -> dict[str, _facade().Any]:
        return dict(value) if isinstance(value, dict) else {}

    def parse_permissions(value: _facade().Any) -> set[str]:
        if isinstance(value, str):
            return {part.strip() for part in value.replace(";", ",").split(",") if part.strip()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return {str(part).strip() for part in value if str(part).strip()}
        return set()

    def access_context(_required_permission: str) -> DatasetAccessContext | None:
        raw_context = params.get("access_context") or runtime_context.get("dataset_access_context")
        context_payload = as_dict(raw_context)
        has_explicit_context = bool(context_payload)
        tenant_id = str(
            context_payload.get("tenant_id")
            or runtime_context.get("dataset_tenant_id")
            or runtime_context.get("tenant_id")
            or runtime_context.get("workspace_id")
            or ""
        ).strip()
        actor_id = str(
            context_payload.get("actor_id")
            or context_payload.get("user_id")
            or params.get("actor_id")
            or params.get("user_id")
            or runtime_context.get("user_id")
            or ""
        ).strip()
        permissions = parse_permissions(context_payload.get("permissions"))
        permissions.update(parse_permissions(params.get("permissions")))
        permissions.update(parse_permissions(runtime_context.get("dataset_permissions")))
        is_admin = as_bool(
            params.get("dataset_admin")
            if "dataset_admin" in params
            else context_payload.get("is_admin", context_payload.get("admin")),
            default=False,
        ) or as_bool(runtime_context.get("dataset_admin"), default=False)
        if not has_explicit_context and (not permissions) and (not is_admin):
            return None
        return DatasetAccessContext(
            actor_id=actor_id,
            tenant_id=tenant_id,
            permissions=frozenset(permissions),
            is_admin=is_admin,
        )

    def finalize(
        result: dict[str, _facade().Any], **defaults: _facade().Any
    ) -> dict[str, _facade().Any]:
        result.setdefault("success", bool(result.get("success", False)))
        for key, value in defaults.items():
            result.setdefault(key, value)
        return result

    if action == "ingest_document":
        result = service.ingest_document(
            dataset_id=dataset_id,
            source=str(params.get("source") or ""),
            text=str(params.get("text") or ""),
            file_path=str(params.get("file_path") or ""),
            document_id=str(params.get("document_id") or ""),
            chunk_strategy=str(params.get("chunk_strategy") or "semantic"),
            chunk_size=as_int(params.get("chunk_size"), 500),
            chunk_overlap=as_int(params.get("chunk_overlap"), 50),
            metadata=as_dict(params.get("metadata")),
            tenant_id=str(params.get("tenant_id") or ""),
            version=params.get("version") or "",
            version_label=str(params.get("version_label") or ""),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id)
    if action == "query":
        query = str(params.get("query") or params.get("question") or user_message or "").strip()
        if not query:
            return {"success": False, "message": "dataset_rag.query 缺少 query 参数"}
        top_k = as_int(params.get("top_k"), 5)
        tenant_id = str(params.get("tenant_id") or "")
        version = params.get("version") or ""
        metadata_filter = as_dict(params.get("metadata_filter"))
        rerank = as_bool(params.get("rerank"), default=False)
        read_context = access_context(DATASET_READ_PERMISSION)
        include_answer = as_bool(params.get("include_answer"), default=True)
        if include_answer:
            result = service.answer(
                dataset_id=dataset_id,
                query=query,
                top_k=top_k,
                tenant_id=tenant_id,
                version=version,
                metadata_filter=metadata_filter,
                rerank=rerank,
                access_context=read_context,
            )
        else:
            result = service.query(
                dataset_id=dataset_id,
                query=query,
                top_k=top_k,
                tenant_id=tenant_id,
                version=version,
                metadata_filter=metadata_filter,
                rerank=rerank,
                access_context=read_context,
            )
        return finalize(
            result, dataset_id=dataset_id, query=query, chunks=[], citations=[], answer=""
        )
    if action == "diff_versions":
        source = str(params.get("source") or "").strip()
        from_version = params.get("from_version") or ""
        if not source:
            return {"success": False, "message": "dataset_rag.diff_versions 缺少 source 参数"}
        if not from_version:
            return {"success": False, "message": "dataset_rag.diff_versions 缺少 from_version 参数"}
        result = service.diff_versions(
            dataset_id=dataset_id,
            source=source,
            tenant_id=str(params.get("tenant_id") or ""),
            from_version=from_version,
            to_version=params.get("to_version") or "latest",
            access_context=access_context(DATASET_READ_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, source=source)
    if action == "rollback_version":
        source = str(params.get("source") or "").strip()
        target_version = params.get("target_version") or ""
        if not source:
            return {"success": False, "message": "dataset_rag.rollback_version 缺少 source 参数"}
        if not target_version:
            return {
                "success": False,
                "message": "dataset_rag.rollback_version 缺少 target_version 参数",
            }
        result = service.rollback_document_version(
            dataset_id=dataset_id,
            source=source,
            tenant_id=str(params.get("tenant_id") or ""),
            target_version=target_version,
            metadata=as_dict(params.get("metadata")),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, source=source)
    if action == "rebuild_index":
        result = service.start_rebuild_index(
            dataset_id=dataset_id,
            tenant_id=str(params.get("tenant_id") or ""),
            metadata_filter=as_dict(params.get("metadata_filter")),
            background=as_bool(params.get("background"), default=True),
            max_attempts=as_int(params.get("max_attempts"), 1),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id)
    if action == "cancel_rebuild":
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return {"success": False, "message": "dataset_rag.cancel_rebuild 缺少 job_id 参数"}
        result = service.cancel_rebuild_job(
            dataset_id, job_id, access_context=access_context(DATASET_WRITE_PERMISSION)
        )
        return finalize(result, dataset_id=dataset_id, job_id=job_id)
    if action == "delete_document":
        document_id = str(params.get("document_id") or "").strip()
        if not document_id:
            return {
                "success": False,
                "message": "dataset_rag.delete_document 缺少 document_id 参数",
            }
        result = service.delete_document(
            dataset_id, document_id, access_context=access_context(DATASET_WRITE_PERMISSION)
        )
        return finalize(result, dataset_id=dataset_id, document_id=document_id)
    return {"success": False, "message": f"未注册的 dataset_rag 动作: {action}"}


def _registered_router_memory_v2(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services.user_memory_service import get_user_memory_service

    service = get_user_memory_service()
    user_id = str(
        params.get("user_id") or params.get("userId") or runtime_context.get("user_id") or "default"
    ).strip()
    if not user_id:
        return {"success": False, "message": f"memory_v2.{action} 缺少 user_id 参数"}

    def as_float(value: _facade().Any, default: float) -> tuple[float, str]:
        if value in (None, ""):
            return (default, "")
        try:
            return (float(value), "")
        except (TypeError, ValueError):
            return (default, "confidence 必须是数字")

    if action == "propose_candidate":
        memory_type = str(params.get("memory_type") or params.get("type") or "preference").strip()
        key = str(params.get("key") or "").strip()
        if not key:
            return {"success": False, "message": "memory_v2.propose_candidate 缺少 key 参数"}
        if "value" not in params:
            return {"success": False, "message": "memory_v2.propose_candidate 缺少 value 参数"}
        confidence, error = as_float(params.get("confidence"), 0.5)
        if error:
            return {"success": False, "message": error}
        try:
            return service.propose_memory_candidate(
                user_id,
                memory_type,
                key,
                params.get("value"),
                source=str(params.get("source") or "memory_v2_api"),
                confidence=confidence,
                evidence=params.get("evidence")
                if isinstance(params.get("evidence"), list)
                else None,
            )
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
    memory_id = str(params.get("memory_id") or params.get("id") or "").strip()
    if not memory_id:
        return {"success": False, "message": f"memory_v2.{action} 缺少 memory_id 参数"}
    if action == "confirm":
        correction = (
            params.get("correction") if isinstance(params.get("correction"), dict) else None
        )
        return service.confirm_memory_candidate(user_id, memory_id, correction=correction)
    if action == "reject":
        return service.reject_memory_candidate(
            user_id, memory_id, reason=str(params.get("reason") or "")
        )
    if action == "correct":
        return service.correct_memory(
            user_id,
            memory_id,
            value=params.get("value") if "value" in params else None,
            key=str(params.get("key")) if "key" in params else None,
            reason=str(params.get("reason") or ""),
        )
    if action == "delete":
        return service.delete_memory(user_id, memory_id, reason=str(params.get("reason") or ""))
    return {"success": False, "message": f"未注册的 memory_v2 动作: {action}"}
