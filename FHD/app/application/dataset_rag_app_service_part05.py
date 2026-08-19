# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.dataset_rag_app_service')

def get_dataset_rag_app_service() -> _facade().DatasetRagApplicationService:
    global _dataset_rag_app_service
    if _facade()._dataset_rag_app_service is None:
        with _facade()._dataset_rag_lock:
            if _facade()._dataset_rag_app_service is None:
                _facade()._dataset_rag_app_service = _facade().DatasetRagApplicationService()
    return _facade()._dataset_rag_app_service

def reset_dataset_rag_app_service_for_tests() -> None:
    global _dataset_rag_app_service
    with _facade()._dataset_rag_lock:
        _facade()._dataset_rag_app_service = None
