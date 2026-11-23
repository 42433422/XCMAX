"""SELECT-only infrastructure adapters over existing SQLAlchemy authorities and RBAC."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentRunRecord, AgentTaskRecord
from app.db.models.ai_employee import AiEmployeeProfile
from app.db.models.customer import Customer
from app.db.models.finance import FinancialTransaction
from app.db.models.inventory import InventoryTransaction
from app.db.models.mrp import ManufacturingOrder
from app.db.models.sales import SalesOrder
from app.db.models.user import User
from app.domain.enterprise_cognition.catalog import EntityDefinition
from app.infrastructure.auth.enterprise_scope import SourceScope

_T = TypeVar("_T")

_MODELS: dict[str, Any] = {
    "order": SalesOrder,
    "customer": Customer,
    "employee": AiEmployeeProfile,
    "task": AgentTaskRecord,
    "fund": FinancialTransaction,
    "inventory": InventoryTransaction,
    "production": ManufacturingOrder,
}
_FIELDS = {
    "order": (
        "id",
        "order_no",
        "customer_id",
        "state",
        "status",
        "invoice_status",
        "payment_state",
        "total_amount",
        "paid_amount",
        "currency",
        "remark",
        "backorder_of_id",
        "return_of_id",
    ),
    "customer": (
        "id",
        "customer_name",
        "credit_limit",
        "credit_used",
        "is_credit_limited",
    ),
    "employee": ("employee_id", "display_name", "mod_id", "user_id", "owner_user_id"),
    "task": (
        "task_id",
        "title",
        "status",
        "attention_state",
        "active_run_id",
        "root_run_id",
        "attempt",
        "run_count",
    ),
    "inventory": (
        "id",
        "ledger_id",
        "product_id",
        "warehouse_id",
        "location_id",
        "transaction_type",
        "quantity",
        "before_quantity",
        "after_quantity",
        "transaction_date",
        "sales_order_id",
        "sales_order_item_id",
    ),
    "production": (
        "id",
        "order_no",
        "bom_id",
        "product_id",
        "product_name",
        "quantity",
        "warehouse_id",
        "status",
    ),
    "fund": (
        "id",
        "transaction_type",
        "amount",
        "currency",
        "reference_type",
        "reference_id",
        "journal_entry_id",
        "status",
        "due_date",
        "transaction_date",
        "counterparty_id",
    ),
}


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class AuthorityReader:
    def __init__(
        self, host_session_factory=None, permission_loader=None, business_session_factory=None
    ):
        if host_session_factory is None:
            from app.db import HostSessionLocal

            host_session_factory = HostSessionLocal
        self.host_session_factory = host_session_factory
        if business_session_factory is None:
            from app.db import SessionLocal

            business_session_factory = SessionLocal
        self.business_session_factory = business_session_factory
        self.permission_loader = permission_loader

    def authorize(self, scope: SourceScope, definition: EntityDefinition) -> None:
        scope.validate()
        with self.host_session_factory() as db:
            actor = db.scalar(
                select(User).where(
                    User.id == int(scope.actor_id),
                    User.tenant_id == scope.tenant_id,
                    User.is_active.is_(True),
                )
            )
            if actor is None:
                raise PermissionError("enterprise_identity_required")
            if definition.permission:
                if self.permission_loader is None:
                    from app.domain.shared_services.auth_service import get_auth_service

                    permissions = get_auth_service().get_user_permissions(actor)
                else:
                    permissions = self.permission_loader(actor)
                if definition.permission not in permissions:
                    raise PermissionError("enterprise_permission_denied")

    def _statement(self, definition: EntityDefinition, scope: SourceScope):
        model = _MODELS[definition.entity_type]
        statement = select(model)
        if definition.entity_type == "employee":
            statement = statement.join(User, User.id == model.owner_user_id).where(
                User.tenant_id == scope.tenant_id,
                model.owner_user_id == int(scope.actor_id),
            )
            if scope.mod_id:
                statement = statement.where(model.mod_id == scope.mod_id)
        else:
            tenant = str(scope.tenant_id) if definition.entity_type == "task" else scope.tenant_id
            statement = statement.where(model.tenant_id == tenant)
            if definition.entity_type == "task":
                statement = statement.where(model.user_id == scope.actor_id)
        return statement

    def _in_source(
        self, db: Session, definition: EntityDefinition, operation: Callable[[Session], _T]
    ) -> _T:
        factory = (
            self.host_session_factory
            if definition.entity_type in {"employee", "task"}
            else self.business_session_factory
        )
        # Source transactions are SELECT-only and separate from the host's
        # derived-view write transaction, even when both resolve to one database.
        with factory() as source:
            return operation(source)

    @staticmethod
    def _task_visible(source, row, scope) -> bool:
        if row is None:
            return False
        if not row.active_run_id:
            return not bool(scope.mod_id)
        run = source.get(AgentRunRecord, row.active_run_id)
        if run is None or run.user_id != scope.actor_id:
            return False
        try:
            payload = json.loads(run.payload_json)
            runtime = payload["metadata"]["runtime_context"]
            binding = runtime.get("_mod_authorization") or {}
            mod_id = binding.get("mod_id") or ""
            return bool(
                str(runtime.get("tenant_id") or "") == str(scope.tenant_id)
                and mod_id == scope.mod_id
                and (not runtime.get("mod_id") or runtime["mod_id"] == mod_id)
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return False

    def visible(self, db, definition: EntityDefinition, scope: SourceScope, entity_id: str) -> bool:
        model = _MODELS[definition.entity_type]
        column = getattr(model, definition.id_field)
        if definition.entity_type == "task":
            return self._in_source(
                db,
                definition,
                lambda source: self._task_visible(
                    source,
                    source.scalar(self._statement(definition, scope).where(column == entity_id)),
                    scope,
                ),
            )
        statement = (
            self._statement(definition, scope).with_only_columns(column).where(column == entity_id)
        )
        return self._in_source(db, definition, lambda source: source.scalar(statement) is not None)

    def list_refs(self, db, definition: EntityDefinition, scope: SourceScope, limit: int) -> dict:
        model = _MODELS[definition.entity_type]
        column = getattr(model, definition.id_field)
        changed_column = (
            model.transaction_date if definition.entity_type == "inventory" else model.updated_at
        )
        statement = (
            self._statement(definition, scope)
            .with_only_columns(column)
            .order_by(changed_column.desc(), column)
            .limit(limit + 1)
        )
        scanned_more = False
        if definition.entity_type == "task":

            def visible_tasks(source):
                rows = list(
                    source.scalars(
                        self._statement(definition, scope)
                        .order_by(model.updated_at.desc(), column)
                        .limit(201)
                    )
                )
                return (
                    [row.task_id for row in rows[:200] if self._task_visible(source, row, scope)],
                    len(rows) > 200,
                )

            ids, scanned_more = self._in_source(db, definition, visible_tasks)
        else:
            ids = self._in_source(db, definition, lambda source: list(source.scalars(statement)))
        return {
            "refs": [
                {"entity_type": definition.entity_type, "entity_id": str(item)}
                for item in ids[:limit]
            ],
            "has_more": scanned_more or len(ids) > limit,
            "source": definition.source,
            "scope": "current_actor_visible_recent",
            "limit": limit,
        }

    def read(
        self, db, definition: EntityDefinition, scope: SourceScope, entity_id: str
    ) -> dict | None:
        model = _MODELS[definition.entity_type]
        statement = (
            self._statement(definition, scope)
            .where(getattr(model, definition.id_field) == entity_id)
            .execution_options(populate_existing=True)
        )

        def load(source: Session) -> dict | None:
            row = source.scalar(statement)
            if row is None or (
                definition.entity_type == "task" and not self._task_visible(source, row, scope)
            ):
                return None
            state = {
                field: json_value(getattr(row, field)) for field in _FIELDS[definition.entity_type]
            }
            if definition.entity_type == "order":
                self._order_quantities(row, scope, state)
            if definition.entity_type == "production":
                fields = ("id", "product_id", "quantity", "consumed_quantity", "unit")
                state["lines"] = [
                    {key: json_value(getattr(line, key)) for key in fields}
                    for line in sorted(row.lines, key=lambda item: item.id)
                    if line.tenant_id == scope.tenant_id
                ]
            # Movement time is not a revision timestamp; never substitute it.
            changed_at = None if definition.entity_type == "inventory" else row.updated_at
            return {"state": state, "source_last_changed": json_value(changed_at)}

        return self._in_source(db, definition, load)

    @staticmethod
    def _order_quantities(row, scope, state):
        fields = (
            "id",
            "product_id",
            "ordered_quantity",
            "reserved_quantity",
            "delivered_quantity",
            "returned_quantity",
            "unit",
            "status",
        )
        items = [item for item in row.items if item.tenant_id == scope.tenant_id]
        state["items"] = [
            {key: json_value(getattr(item, key)) for key in fields}
            for item in sorted(items, key=lambda item: item.id)
        ]
        units = {item.unit for item in items if item.unit}
        known = bool(items) and len(units) == 1 and all(item.unit for item in items)
        state["quantity_unit"] = next(iter(units)) if known else None
        for name in (
            "ordered_quantity",
            "reserved_quantity",
            "delivered_quantity",
            "returned_quantity",
        ):
            state[name] = (
                str(
                    sum(
                        (getattr(item, name) or Decimal(0) for item in items),
                        Decimal(0),
                    )
                )
                if known
                else None
            )
        state["remaining_quantity"] = (
            str(Decimal(state["ordered_quantity"]) - Decimal(state["delivered_quantity"]))
            if known
            else None
        )
        state["fulfillment"] = row.fulfillment_state()
        state["due_at"] = None
        state["delay_status"] = "unknown"
        state["delay_reason"] = "authoritative_due_date_not_available"
