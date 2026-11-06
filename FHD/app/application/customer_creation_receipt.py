"""Bind an executor claim to the customer's existing transactional lifecycle log."""

from contextlib import contextmanager
from contextvars import ContextVar

from app.domain.task_lifecycle.control import SessionBook

CUSTOMER_CREATE_RECEIPTS = "customer_create"
_CREATE_CLAIM: ContextVar[tuple[str, str, str] | None] = ContextVar(
    "customer_create_claim", default=None
)


@contextmanager
def customer_creation_claim(key: str, fingerprint: str, tenant: str):
    """Request data cannot supply the executor's claimed operation."""
    token = _CREATE_CLAIM.set((key, fingerprint, tenant))
    try:
        yield
    finally:
        _CREATE_CLAIM.reset(token)


def record_customer_creation(session, unit) -> None:
    """Stage the row id in the caller's transaction, without committing it."""
    claim = _CREATE_CLAIM.get()
    if claim is None:
        return
    key, fingerprint, tenant = claim
    if not key or not tenant or str(unit.tenant_id) != tenant:
        raise ValueError("客户创建回执与执行租户不一致")
    session.flush()
    SessionBook(session).put(
        CUSTOMER_CREATE_RECEIPTS,
        tenant,
        key,
        {"fingerprint": fingerprint, "customer_id": int(unit.id)},
    )
