"""Application boundary used by HTTP routes for legacy business services.

The underlying implementations still live in ``app.services`` while they are
being migrated.  Keeping the imports and the small amount of orchestration in
this module prevents transport code from depending on that legacy layer.
"""

from __future__ import annotations

from typing import Any


def load_customer_pipeline(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline

    return load_pipeline(market_user_id, username=username)


def save_customer_pipeline(
    document: dict[str, Any], *, strict_crm: bool | None = None
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import save_pipeline

    if strict_crm is None:
        return save_pipeline(document)
    return save_pipeline(document, strict_crm=strict_crm)


def contract_block(document: dict[str, Any]) -> dict[str, Any]:
    from app.services.contract_lifecycle import get_contract_block

    return get_contract_block(document)


def transition_customer_contract(
    document: dict[str, Any], status: str, *, source: str, note: str
) -> dict[str, Any]:
    from app.services.contract_lifecycle import transition_contract

    return transition_contract(document, status, source=source, note=note)


def start_customer_esign(
    document: dict[str, Any],
    *,
    party_a: str,
    party_b: str,
    amount_cents: int | None,
) -> dict[str, Any]:
    from app.services.contract_lifecycle import start_esign_flow

    return start_esign_flow(
        document,
        party_a=party_a,
        party_b=party_b,
        amount_cents=amount_cents,
    )


def sync_contract_crm_metadata(document: dict[str, Any]) -> dict[str, Any]:
    from app.services.contract_lifecycle import apply_contract_to_crm_meta

    return apply_contract_to_crm_meta(document)


def list_crm_invoices(**filters: Any) -> dict[str, Any]:
    from app.services.user_cs_crm_store import list_crm_invoices as _list

    return _list(**filters)


def get_crm_invoice(invoice_id: int) -> dict[str, Any] | None:
    from app.services.user_cs_crm_store import get_crm_invoice_by_id

    return get_crm_invoice_by_id(invoice_id)


def get_customer_opportunity(market_user_id: int) -> dict[str, Any] | None:
    from app.services.user_cs_crm_store import get_opportunity_by_market_user

    return get_opportunity_by_market_user(market_user_id)


def market_user_id_for_opportunity(opportunity_id: int) -> int:
    from app.services.user_cs_crm_store import _connect, ensure_crm_schema

    ensure_crm_schema()
    with _connect() as connection:
        row = connection.execute(
            "SELECT market_user_id FROM cs_crm_opportunities WHERE id = ?",
            (opportunity_id,),
        ).fetchone()
    return int(row["market_user_id"]) if row else 0


def issue_pipeline_invoice(document: dict[str, Any]) -> dict[str, Any]:
    from app.services.tax_invoice_provider import issue_crm_invoice_for_pipeline

    return issue_crm_invoice_for_pipeline(document)


def archive_crm_invoice(invoice: dict[str, Any], *, market_user_id: int) -> dict[str, Any]:
    from app.services.finance_unified_archive import archive_from_crm_invoice

    return archive_from_crm_invoice(invoice, market_user_id=market_user_id)


def recognize_business_intents(text: str) -> dict[str, Any]:
    from app.services.intent_service import recognize_intents

    return recognize_intents(text)
