# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.knowledge_v1")


def _persy_memory_response(
    payload: dict[str, _facade().Any], *, request: _facade().Request, action: str
) -> _facade().JSONResponse:
    success = bool(payload.get("success"))
    code = str(payload.get("error_code") or "")
    status_code = 200 if success else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    elif code == "persy_memory_not_found":
        status_code = 404
    try:
        from app.utils.logging import audit_logger

        access = _facade()._dataset_access_context_from_request(request)
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
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("Persy memory audit unavailable", exc_info=True)
    return _facade().JSONResponse(payload, status_code=status_code)


def _merge_persy_recall(
    payload: dict[str, _facade().Any],
    *,
    request: _facade().Request,
    params: dict[str, _facade().Any],
) -> dict[str, _facade().Any]:
    if str(params.get("dataset_id") or "") != _facade()._PERSY_DATASET_ID or not payload.get(
        "success"
    ):
        return payload
    query_text = str(params.get("query") or "").strip()
    if not query_text:
        return payload
    memory_result = (
        _facade()
        ._persy_memory_service()
        .query(
            access_context=_facade()._dataset_access_context_from_request(request),
            query=query_text,
            top_k=max(1, min(int(params.get("top_k") or 5), 20)),
            reinforce=True,
        )
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
    merged_chunks: list[dict[str, _facade().Any]] = []
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
        dict(citation) for citation in payload.get("citations", []) if isinstance(citation, dict)
    ]
    for chunk in memory_chunks:
        memory_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
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
        result["answer"] = "\n\n".join(part for part in (memory_answer, knowledge_answer) if part)
    return result


def _agent_node_output(run: _facade().Any, node_id: str) -> dict[str, _facade().Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", False) and (not output.get("message")):
        output["message"] = getattr(run, "error", False)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return _facade().cast("dict[str, Any]", _facade()._public_dataset_payload(output))


def _dataset_agent_user_id(request: _facade().Request, params: dict[str, _facade().Any]) -> str:
    access_context = (
        params.get("access_context") if isinstance(params.get("access_context"), dict) else {}
    )
    if not isinstance(access_context, dict):
        access_context = {}
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or access_context.get("actor_id")
        or params.get("actor_id")
        or params.get("user_id")
        or params.get("tenant_id")
        or "dataset-rag-route"
    ).strip()


def _run_dataset_rag_agent(
    *, request: _facade().Request, action: str, params: dict[str, _facade().Any], route_path: str
) -> _facade().JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    data = dict(params or {})
    access_payload = _facade()._dataset_access_payload_from_request(request)
    if access_payload:
        data["access_context"] = access_payload
        if access_payload.get("tenant_id"):
            if not str(data.get("tenant_id") or "").strip():
                data["tenant_id"] = access_payload["tenant_id"]
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("dataset_rag") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return _facade().JSONResponse(
            {"success": False, "message": f"未注册的 Dataset/RAG 动作: {action}"}, status_code=400
        )
    node_id = f"dataset_rag_{action}"
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 dataset_rag.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="dataset_rag",
                action=action,
                params=data,
                risk=_facade().normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute dataset_rag.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=_facade().normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
        metadata={"source": "dataset_rag_route", "route": route_path},
    )
    user_id = _facade()._dataset_agent_user_id(request, data)
    runtime_context = {
        "source": "dataset_rag_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    if access_payload:
        runtime_context["dataset_access_context"] = access_payload
        if access_payload.get("tenant_id"):
            runtime_context["dataset_tenant_id"] = access_payload["tenant_id"]
        runtime_context["dataset_permissions"] = list(access_payload.get("permissions") or [])
        runtime_context["dataset_admin"] = bool(access_payload.get("is_admin"))
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"Dataset/RAG {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "dataset-rag-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    payload = _facade()._agent_node_output(run, node_id)
    if action == "query":
        payload = _facade()._merge_persy_recall(payload, request=request, params=data)
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    elif payload.get("error_code") == "tool_exception":
        status_code = 500
    else:
        status_code = 200
    return _facade().JSONResponse(payload, status_code=status_code)


def _mirror_ingest_to_persy(
    *,
    text: str,
    source: str,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    request: _facade().Request | None = None,
) -> dict[str, _facade().Any]:
    """Dual-write legacy /ingest into governed persy-knowledge dataset."""
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        access = (
            _facade()._dataset_access_context_from_request(request) if request is not None else None
        )
        return _facade().cast(
            "dict[str, Any]",
            get_dataset_rag_app_service().ingest_document(
                dataset_id=_facade()._PERSY_DATASET_ID,
                source=source or "legacy-ingest",
                text=text,
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                metadata={"entrypoint": "legacy_ingest_mirror"},
                access_context=access,
            ),
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("mirror ingest to persy-knowledge failed: %s", exc)
        return {"success": False, "message": str(exc)}
