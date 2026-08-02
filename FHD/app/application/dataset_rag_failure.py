"""Safe failure contracts for Dataset/RAG ingestion."""

from __future__ import annotations

from typing import Any

from app.utils.operational_errors import record_recoverable_failure


def build_dataset_ingest_failure(dataset_id: str) -> dict[str, Any]:
    """Log the active exception and keep the Dataset response free of internals."""
    record_recoverable_failure("Dataset document ingestion")
    return {
        "success": False,
        "dataset_id": dataset_id,
        "message": "资料入库失败，请稍后重试",
        "error_code": "dataset_ingest_failed",
    }
