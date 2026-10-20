# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
import multiprocessing


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


def get_dataset_rag_app_service() -> _facade().DatasetRagApplicationService:
    if _facade()._dataset_rag_app_service is None:
        with _facade()._dataset_rag_lock:
            if _facade()._dataset_rag_app_service is None:
                _facade()._dataset_rag_app_service = _facade().DatasetRagApplicationService(
                    rebuild_workers_enabled=multiprocessing.parent_process() is None
                )
    return _facade()._dataset_rag_app_service


def reset_dataset_rag_app_service_for_tests() -> None:
    from app.application.dataset_rag_queue import stop_host_workers

    if not stop_host_workers():
        raise RuntimeError("dataset host work is still running; retain its storage")
    with _facade()._dataset_rag_lock:
        _facade()._dataset_rag_app_service = None
