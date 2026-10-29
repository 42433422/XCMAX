"""Reviewed Excel template HTTP adapters (split under route soft-cap)."""

from __future__ import annotations

from fastapi import APIRouter

from app.fastapi_routes.reviewed_excel.archive import router as archive_router
from app.fastapi_routes.reviewed_excel_template import router as template_router

router = APIRouter()
router.include_router(archive_router)
router.include_router(template_router)
