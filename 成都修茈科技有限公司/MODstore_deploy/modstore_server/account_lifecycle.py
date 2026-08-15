"""Canonical registration, payment, entitlement, and desktop-access lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.account_license_plans import (
    account_license_plan,
    is_account_license_plan_id,
)
from modstore_server.datetime_utils import as_utc_aware
from modstore_server.models import User, UserPlan, get_session_factory

ACCOUNT_PENDING_PLAN = "pending_plan"
ACCOUNT_PENDING_PAYMENT = "pending_payment"
ACCOUNT_ACTIVE = "active"
ACCOUNT_SUSPENDED = "suspended"

VALID_ACCOUNT_STATES = {
    ACCOUNT_PENDING_PLAN,
    ACCOUNT_PENDING_PAYMENT,
    ACCOUNT_ACTIVE,
    ACCOUNT_SUSPENDED,
}


@dataclass(frozen=True)
class AccountLifecycle:
    account_state: str
    next_action: str
    desktop_access: bool
    active_plan_id: str
    account_tier: str
    activation_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _active_plan(
    session: Session, user_id: int, *, account_license: bool
) -> UserPlan | None:
    now = datetime.now(timezone.utc)
    rows = (
        session.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active.is_(True))
        .order_by(UserPlan.id.desc())
        .all()
    )
    for row in rows:
        if is_account_license_plan_id(row.plan_id) != account_license:
            continue
        expires_at = as_utc_aware(row.expires_at) if row.expires_at else None
        if expires_at is None or expires_at > now:
            return row
    return None


def _stored_state(user: User) -> str:
    value = str(getattr(user, "account_state", "") or "").strip().lower()
    return value if value in VALID_ACCOUNT_STATES else ACCOUNT_PENDING_PLAN


def lifecycle_for_user(session: Session, user: User) -> AccountLifecycle:
    """Resolve access from durable identity plus current entitlement state.

    ``is_enterprise`` remains a compatibility grant for manually provisioned
    accounts. Paid access is derived from an unexpired active ``UserPlan`` so a
    payment does not create another permanent authorization truth source.
    """

    plan = _active_plan(session, int(user.id), account_license=True)
    if bool(getattr(user, "is_admin", False)):
        return AccountLifecycle(ACCOUNT_ACTIVE, "open_workbench", True, "", "", "admin")
    if plan is not None:
        meta = account_license_plan(plan.plan_id) or {}
        return AccountLifecycle(
            ACCOUNT_ACTIVE,
            "return_desktop_login",
            True,
            str(plan.plan_id or ""),
            str(meta.get("account_tier") or "normal"),
            "active_plan",
        )
    if bool(getattr(user, "is_enterprise", False)):
        return AccountLifecycle(
            ACCOUNT_ACTIVE,
            "return_desktop_login",
            True,
            "",
            "normal",
            "legacy_enterprise_grant",
        )

    state = _stored_state(user)
    if state == ACCOUNT_SUSPENDED:
        return AccountLifecycle(state, "contact_support", False, "", "", "suspended")
    if state == ACCOUNT_PENDING_PAYMENT:
        return AccountLifecycle(
            state, "complete_payment", False, "", "", "registration"
        )
    return AccountLifecycle(
        ACCOUNT_PENDING_PLAN,
        "select_plan",
        False,
        "",
        "",
        "registration",
    )


def active_membership_plan(session: Session, user_id: int) -> UserPlan | None:
    """Return the active VIP/SVIP membership without conflating account access."""

    return _active_plan(session, user_id, account_license=False)


def lifecycle_for_user_id(user_id: int) -> AccountLifecycle:
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            raise LookupError("account_not_found")
        return lifecycle_for_user(session, user)


def mark_pending_payment(
    user_id: int,
    *,
    plan_id: str,
    session: Session | None = None,
) -> None:
    if not is_account_license_plan_id(plan_id):
        return
    owns_session = session is None
    if session is None:
        session = get_session_factory()()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            return
        current = lifecycle_for_user(session, user)
        if not current.desktop_access:
            user.account_state = ACCOUNT_PENDING_PAYMENT
            session.add(user)
        if owns_session:
            session.commit()
    finally:
        if owns_session:
            session.close()


def mark_active_after_plan(user: User, *, plan_id: str, session: Session) -> None:
    """Persist the lifecycle transition inside the payment transaction."""

    if not is_account_license_plan_id(plan_id):
        return
    user.account_state = ACCOUNT_ACTIVE
    session.add(user)
