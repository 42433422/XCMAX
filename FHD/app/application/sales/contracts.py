"""The narrow service interfaces required by an atomic sales workflow."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

SessionFactory = Callable[[], AbstractContextManager[Session]]


class ClosedLoopExecutionError(RuntimeError):
    """A failed workflow step; propagating it rolls back the caller transaction."""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


class Quote(Protocol):
    def __call__(self, data: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]: ...


class Confirm(Protocol):
    def __call__(self, order_id: int, *, db: Session | None = None) -> dict[str, Any]: ...


class Deliver(Protocol):
    def __call__(
        self,
        order_id: int,
        item_id: int,
        quantity: Decimal | float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        idempotency_key: str | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]: ...


class Invoice(Protocol):
    def __call__(
        self,
        order_id: int,
        *,
        amount: Decimal | float | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]: ...


class Payment(Protocol):
    def __call__(
        self,
        order_id: int,
        amount: Decimal | float | None = None,
        *,
        db: Session | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SalesOperations:
    quote: Quote
    confirm: Confirm
    deliver: Deliver
    invoice: Invoice
    payment: Payment


class InventorySource(Protocol):
    def __call__(
        self,
        db: Session,
        *,
        product_id: int,
        warehouse_id: int,
        quantity: Decimal,
        tenant_id: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReferencePorts:
    customer: Callable[[Session, dict[str, Any], int], dict[str, Any]]
    products: Callable[[Session, dict[str, Any], int], list[dict[str, Any]]]
    warehouse: Callable[[Session, dict[str, Any], int], dict[str, Any]]
    inventory: InventorySource


class CompositeFingerprint(Protocol):
    def __call__(
        self,
        customer: dict[str, Any],
        products: list[dict[str, Any]],
        warehouse: dict[str, Any],
        order: dict[str, Any],
        fulfillment: dict[str, Any],
        invoice: dict[str, Any],
        pa: dict[str, Any],
    ) -> str: ...


@dataclass(frozen=True)
class FingerprintPorts:
    build: CompositeFingerprint
    persist: Callable[[Session, int, str], None]
    verify: Callable[[Session, int, str], None]
