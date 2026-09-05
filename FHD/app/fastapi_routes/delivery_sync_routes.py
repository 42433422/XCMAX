"""Authenticated background reconciliation of accepted private deliveries."""

from fastapi import APIRouter, Request

from app.application.private_delivery_sync import sync_private_deliveries

router = APIRouter(tags=["mod-store", "private-delivery"])


@router.post("/private-delivery/sync")
async def private_delivery_sync(request: Request) -> dict:
    return {"success": True, "data": await sync_private_deliveries(request)}
