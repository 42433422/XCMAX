"""SQLAlchemy commit observers preserve the original business transaction and data.

Bulk SQL/external writers are intentionally not inferred; bounded TTL queries repair
missed events. Nested rollbacks discard only their own pending identities.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentRunRecord, AgentTaskRecord
from app.db.models.ai_employee import AiEmployeeProfile
from app.db.models.customer import Customer
from app.db.models.finance import FinancialTransaction
from app.db.models.inventory import InventoryTransaction
from app.db.models.mrp import ManufacturingOrder, ManufacturingOrderLine
from app.db.models.purchase import (
    PurchaseInbound,
    PurchaseInboundItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.user import User
from app.request_active_mod_ctx import get_request_active_mod_id, normalize_active_mod_id
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_PENDING = "enterprise_committed_entity_identities"
_MODELS = {
    SalesOrder: ("order", "id", "sales_orders"),
    SalesOrderItem: ("order", "order_id", "sales_orders"),
    Customer: ("customer", "id", "customers"),
    AiEmployeeProfile: ("employee", "employee_id", "ai_employee_profiles"),
    AgentTaskRecord: ("task", "task_id", "agent_tasks"),
    FinancialTransaction: ("fund", "id", "financial_transactions"),
    Supplier: ("supplier", "id", "suppliers"),
    PurchaseOrder: ("purchase_order", "id", "purchase_orders"),
    PurchaseOrderItem: ("purchase_order", "order_id", "purchase_orders"),
    PurchaseInbound: ("purchase_inbound", "id", "purchase_inbounds"),
    PurchaseInboundItem: ("purchase_inbound", "inbound_id", "purchase_inbounds"),
    InventoryTransaction: ("inventory", "id", "inventory_transactions"),
    ManufacturingOrder: ("production", "id", "manufacturing_orders"),
    ManufacturingOrderLine: ("production", "order_id", "manufacturing_orders"),
}


def _source_mods(session, row) -> tuple[str, ...]:
    if isinstance(row, AiEmployeeProfile):
        # Host employee queries include owned profiles across Mods; a Mod query
        # is limited to its own profile. Both views must expire after a change.
        mod_id = row.mod_id or ""
        if not isinstance(mod_id, str) or normalize_active_mod_id(mod_id) != mod_id:
            return ("",)
        return tuple(dict.fromkeys(("", mod_id)))
    if isinstance(row, AgentTaskRecord):
        if not row.active_run_id:
            return ("",)
        payload = session.scalar(
            select(AgentRunRecord.payload_json).where(
                AgentRunRecord.run_id == row.active_run_id,
                AgentRunRecord.user_id == row.user_id,
            )
        )
        try:
            runtime = json.loads(payload)["metadata"]["runtime_context"]
            mod_id = (runtime.get("_mod_authorization") or {}).get("mod_id") or ""
            if (
                str(runtime.get("tenant_id") or "") != str(row.tenant_id)
                or not isinstance(mod_id, str)
                or normalize_active_mod_id(mod_id) != mod_id
                or str(runtime.get("mod_id") or "") != mod_id
            ):
                return ()
            return (mod_id,)
        except (ValueError, KeyError, TypeError, AttributeError):
            return ()
    return (get_request_active_mod_id(),)


def _capture(session, flush_context) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    pending = session.info.setdefault(_PENDING, {}).setdefault(transaction, {})
    for row in session.new | session.dirty | session.deleted:
        spec = _MODELS.get(type(row))
        if spec is None:
            continue
        tenant = getattr(row, "tenant_id", None)
        if isinstance(row, AiEmployeeProfile):
            tenant = session.scalar(select(User.tenant_id).where(User.id == row.owner_user_id))
        if isinstance(tenant, bool) or not str(tenant or "").isdigit() or int(str(tenant)) <= 0:
            continue
        entity_type, id_field, source = spec
        entity_id = str(getattr(row, id_field) or "")
        if not entity_id:
            continue
        for mod_id in _source_mods(session, row):
            key = (int(str(tenant)), mod_id, entity_type, entity_id)
            pending[key] = {
                "tenant_id": int(str(tenant)),
                "mod_id": mod_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "source_table": source,
            }


def _committed(session) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    pending = session.info.get(_PENDING, {})
    identities = pending.pop(transaction, {})
    if transaction is not None and transaction.nested:
        pending.setdefault(transaction.parent, {}).update(identities)
        return
    session.info.pop(_PENDING, None)
    from app.neuro_bus.application_neuro_bridge import publish_neuro_event

    for identity in identities.values():
        try:
            published = publish_neuro_event("enterprise.entity_changed", identity, "enterprise")
            if not published:
                logger.warning(
                    "enterprise state event unavailable; authoritative TTL refresh remains active"
                )
        except RECOVERABLE_ERRORS:
            # The transaction is committed. Publishing must not report it as failed.
            logger.warning("enterprise state event failed after business commit", exc_info=True)


def _rolled_back(session, previous_transaction) -> None:
    pending = session.info.get(_PENDING, {})
    for transaction in list(pending):
        ancestor = transaction
        while ancestor is not None:
            if ancestor is previous_transaction:
                pending.pop(transaction, None)
                break
            ancestor = ancestor.parent
    if not pending:
        session.info.pop(_PENDING, None)


def install_source_observer() -> None:
    for name, handler in (
        ("after_flush", _capture),
        ("after_commit", _committed),
        ("after_soft_rollback", _rolled_back),
    ):
        if not event.contains(Session, name, handler):
            event.listen(Session, name, handler)
