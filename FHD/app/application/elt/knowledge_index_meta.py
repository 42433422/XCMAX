"""Knowledge document write vs vector-index status (not interchangeable)."""

from __future__ import annotations

from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _knowledge_index_meta(tenant_id: int | str) -> dict[str, Any]:
    """Document write ≠ vector index. Never treat embedding_count=0 as missing docs."""
    rag_enabled = False
    embedding_count = 0
    try:
        from app.infrastructure.rag import is_rag_enabled

        rag_enabled = bool(is_rag_enabled())
    except RECOVERABLE_ERRORS:
        rag_enabled = False
    try:
        from app.application.dataset_rag_app_service import (
            DATASET_READ_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        status = get_dataset_rag_app_service().status(
            dataset_id="office-docking",
            tenant_id=str(tenant_id),
            access_context=DatasetAccessContext(
                actor_id="",
                tenant_id=str(tenant_id),
                permissions=frozenset({DATASET_READ_PERMISSION}),
            ),
            include_documents=False,
        )
        index = status.get("index") if isinstance(status, dict) else {}
        if isinstance(index, dict):
            embedding_count = int(index.get("embedding_count") or 0)
    except RECOVERABLE_ERRORS:
        embedding_count = 0
    return {"rag_enabled": rag_enabled, "embedding_count": embedding_count}


def enrich_knowledge_progress(
    kb_receipt: dict[str, Any],
    tenant_id: int | str,
    progress_factory,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Split document write from vector index in receipt + progress payload."""
    rag_meta = _knowledge_index_meta(tenant_id)
    kb_receipt = {
        **kb_receipt,
        "document_written": kb_receipt.get("action") in {"new", "update"},
        "rag_enabled": rag_meta["rag_enabled"],
        "embedding_count": rag_meta["embedding_count"],
    }
    if kb_receipt.get("action") == "skip":
        kb_message = str(kb_receipt.get("reason") or "知识库跳过写入")
    elif kb_receipt.get("document_written"):
        if rag_meta["rag_enabled"] and rag_meta["embedding_count"] > 0:
            kb_message = "文档已写入；向量索引已建立"
        elif rag_meta["rag_enabled"]:
            kb_message = "文档已写入；向量索引尚未建立（不等于文档未写入）"
        else:
            kb_message = "文档已写入；语义检索未启用（不等于文档未写入）"
    else:
        kb_message = str(kb_receipt.get("reason") or "知识库未写入文档")
    kb_done = progress_factory(
        "done" if kb_receipt.get("action") != "skip" else "skipped",
        100,
        message=kb_message,
    )
    kb_done["document_written"] = bool(kb_receipt.get("document_written"))
    kb_done["rag_enabled"] = bool(rag_meta["rag_enabled"])
    kb_done["embedding_count"] = int(rag_meta["embedding_count"])
    return kb_receipt, kb_done, rag_meta


def business_completion_from_run(
    run: dict[str, Any],
    progress_factory,
) -> tuple[str, dict[str, Any]]:
    """Map ETL completed runs with 0 written rows to completed_empty (not applied)."""
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    executed = int(summary.get("executed") or run.get("executed_rows") or 0)
    written = (
        executed
        + int(summary.get("new") or run.get("new_rows") or 0)
        + int(summary.get("update") or run.get("update_rows") or 0)
    )
    receipt = run.get("receipt") if isinstance(run.get("receipt"), dict) else {}
    if written <= 0 and not receipt.get("rows_written"):
        return (
            "completed_empty",
            progress_factory(
                "done",
                100,
                message="执行结束但未写入任何业务行（无报错≠已入库）",
            ),
        )
    return "applied", progress_factory("done", 100, message="业务写入已完成")
