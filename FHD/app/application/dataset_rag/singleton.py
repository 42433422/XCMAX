from __future__ import annotations

import threading

from .service import DatasetRagApplicationService

_dataset_rag_app_service: DatasetRagApplicationService | None = None
_dataset_rag_lock = threading.Lock()


def get_dataset_rag_app_service() -> DatasetRagApplicationService:
    global _dataset_rag_app_service
    if _dataset_rag_app_service is None:
        with _dataset_rag_lock:
            if _dataset_rag_app_service is None:
                _dataset_rag_app_service = DatasetRagApplicationService()
    return _dataset_rag_app_service


def reset_dataset_rag_app_service_for_tests() -> None:
    global _dataset_rag_app_service
    with _dataset_rag_lock:
        _dataset_rag_app_service = None
