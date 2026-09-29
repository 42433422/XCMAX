from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.bootstrap import get_shipment_application_service_core
from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert
from app.infrastructure.tenant_scope import TenantScopeError
from app.utils.operational_errors import RECOVERABLE_ERRORS

_QUIET = (HTTPException, TenantScopeError, SQLAlchemyError, *RECOVERABLE_ERRORS)


def remember_business_shipment(payload: dict) -> dict:
    unit = str(payload.get("unit_name") or "").strip()
    if not unit:
        return {"success": False}
    try:
        _customer_pg_insert(
            unit,
            str(payload.get("contact_person") or ""),
            str(payload.get("contact_phone") or ""),
            "",
        )
    except _QUIET:
        pass
    try:
        saved = get_shipment_application_service_core().record_created_shipment(
            unit_name=unit,
            items=list(payload.get("items") or []),
            contact_person=str(payload.get("contact_person") or ""),
            contact_phone=str(payload.get("contact_phone") or ""),
        )
    except _QUIET:
        return {"success": False}
    return saved if isinstance(saved, dict) else {"success": False}
