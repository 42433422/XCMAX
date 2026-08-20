"""Shared FastAPI router for the Python payment fallback modules."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/payment", tags=["payment"])
