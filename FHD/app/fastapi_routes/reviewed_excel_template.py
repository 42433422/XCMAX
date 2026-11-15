"""Tenant- and owner-scoped workbook reviews backed by existing ETL records.

Compatibility facade over the ``reviewed_excel`` route package. The HTTP
endpoints live in focused submodules (<= 20 routes each); this module keeps the
historical import and patch surface stable for adapters, tests and
``reviewed_excel.archive``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.fastapi_routes.reviewed_excel import (
    analysis,
    analysis_body,
    app_gateway,
    candidates,
    classifications,
    classify,
    intake,
    preview,
    save,
    support,
)
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
router.include_router(classify.router)
router.include_router(classifications.router)
router.include_router(candidates.router)
router.include_router(analysis.router)
router.include_router(preview.router)
router.include_router(intake.router)
router.include_router(save.router)

_MODULES = (
    support,
    app_gateway,
    classify,
    classifications,
    candidates,
    analysis,
    analysis_body,
    preview,
    intake,
    save,
)


def __getattr__(name: str):
    # Resolve lazily so monkeypatching the owning module stays visible through
    # the historical facade import path.
    for module in _MODULES:
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
