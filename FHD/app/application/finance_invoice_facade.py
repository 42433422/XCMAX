"""Application boundary for self-hosted finance invoice routes."""

from __future__ import annotations

from typing import Any


def list_crm_invoices(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.user_cs_crm_store import list_crm_invoices as implementation

    return implementation(*args, **kwargs)


def get_crm_invoice_by_id(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from app.services.user_cs_crm_store import get_crm_invoice_by_id as implementation

    return implementation(*args, **kwargs)


def get_opportunity_by_market_user(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from app.services.user_cs_crm_store import get_opportunity_by_market_user as implementation

    return implementation(*args, **kwargs)


def market_user_id_for_opportunity(opportunity_id: int) -> int:
    from app.services.user_cs_crm_store import _connect, ensure_crm_schema

    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT market_user_id FROM cs_crm_opportunities WHERE id = ?",
            (int(opportunity_id),),
        ).fetchone()
    return int(row["market_user_id"]) if row else 0


def load_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline as implementation

    return implementation(*args, **kwargs)


def save_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.user_cs_pipeline import save_pipeline as implementation

    return implementation(*args, **kwargs)


def issue_crm_invoice_for_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.tax_invoice_provider import issue_crm_invoice_for_pipeline as implementation

    return implementation(*args, **kwargs)


def archive_from_crm_invoice(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.finance_unified_archive import archive_from_crm_invoice as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "archive_from_crm_invoice",
    "get_crm_invoice_by_id",
    "get_opportunity_by_market_user",
    "issue_crm_invoice_for_pipeline",
    "list_crm_invoices",
    "load_pipeline",
    "market_user_id_for_opportunity",
    "save_pipeline",
]
