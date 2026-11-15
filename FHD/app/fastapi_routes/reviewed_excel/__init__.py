"""Reviewed Excel template HTTP adapters (split under route soft-cap)."""

from __future__ import annotations

from fastapi import APIRouter

from app.fastapi_routes.reviewed_excel import (
    analysis,
    candidates,
    classifications,
    classify,
    intake,
    preview,
    save,
)
from app.fastapi_routes.reviewed_excel.archive import router as archive_router

router = APIRouter()
router.include_router(archive_router)
router.include_router(classify.router)
router.include_router(classifications.router)
router.include_router(candidates.router)
router.include_router(analysis.router)
router.include_router(preview.router)
router.include_router(intake.router)
router.include_router(save.router)
