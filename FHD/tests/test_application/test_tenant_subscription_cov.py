"""Extended coverage tests for tenant_subscription_app_service.

Covers the missing branches in provision_trial_for_user, sync_tenant_display_name,
subscription_status_for_user, apply_paid_plan_to_tenant, and apply_paid_plan_for_user.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.application.tenant_subscription_app_service import (
    _slug_code,
    apply_paid_plan_for_user,
    apply_paid_plan_to_tenant,
    provision_trial_for_user,
    subscription_status_for_user,
    sync_tenant_display_name,
)

# ---------------------------------------------------------------------------
# _slug_code
# ---------------------------------------------------------------------------


def test_slug_code_normal():
    assert _slug_code("MyCompany") == "mycompany"


def test_slug_code_special_chars():
    assert _slug_code("Hello World!") == "hello-world"


def test_slug_code_empty_string():
    assert _slug_code("") == "tenant"


def test_slug_code_only_symbols():
    result = _slug_code("!@#$%")
    assert result == "tenant"


def test_slug_code_long_name():
    long = "a" * 100
    result = _slug_code(long)
    assert len(result) <= 48


# ---------------------------------------------------------------------------
# provision_trial_for_user
# ---------------------------------------------------------------------------


def _make_db_ctx(db: MagicMock):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_provision_trial_user_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = provision_trial_for_user(user_id=99, username="nobody")

    assert result is None


def test_provision_trial_user_already_has_tenant():
    existing_tenant = MagicMock(id=42)
    user = MagicMock(id=5, tenant_id=42)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, existing_tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = provision_trial_for_user(user_id=5, username="alice")

    assert result == 42


def test_provision_trial_user_tenant_id_but_tenant_missing():
    """tenant_id set but tenant deleted — should fall through and create new."""
    user = MagicMock(id=5, tenant_id=7)
    user.tenant_id = 7

    call_order = [user, None]  # second call for Tenant.id==7 returns None

    db = MagicMock()
    # query(User).filter().first() -> user
    # query(Tenant).filter(id==7).first() -> None
    # query(Tenant).filter(code==...).first() -> None (no collision)
    db.query.return_value.filter.return_value.first.side_effect = [user, None, None]

    def _assign_pk(obj):
        obj.id = 88

    db.add.side_effect = _assign_pk

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch("app.application.tenant_subscription_app_service.trial_days", return_value=7):
            result = provision_trial_for_user(user_id=5, username="bob")

    assert result == 88


def test_provision_trial_code_collision():
    """Slug collision forces suffix loop."""
    user = MagicMock(id=5, tenant_id=None)

    collision_tenant = MagicMock()
    call_results = [
        user,  # User lookup
        collision_tenant,  # code 'bob' collides
        None,  # code 'bob-1' is free
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = call_results

    def _assign_pk(obj):
        obj.id = 55

    db.add.side_effect = _assign_pk

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch("app.application.tenant_subscription_app_service.trial_days", return_value=7):
            result = provision_trial_for_user(user_id=5, username="bob")

    assert result == 55


def test_provision_trial_neuro_notify_error_suppressed():
    """neuro_notify raising a recoverable error should be swallowed."""
    user = MagicMock(id=5, tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, None]

    def _assign_pk(obj):
        obj.id = 10

    db.add.side_effect = _assign_pk

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch("app.application.tenant_subscription_app_service.trial_days", return_value=7):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_tenant_changed",
                side_effect=RuntimeError("bus down"),
            ):
                # Should not raise even though neuro_notify fails
                result = provision_trial_for_user(user_id=5, username="carol")

    assert result == 10


# ---------------------------------------------------------------------------
# sync_tenant_display_name
# ---------------------------------------------------------------------------


def test_sync_tenant_display_name_blank_brand():
    result = sync_tenant_display_name(user_id=1, company_brand="   ")
    assert result == ""


def test_sync_tenant_display_name_user_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = sync_tenant_display_name(user_id=99, company_brand="Acme")

    assert result == "Acme"


def test_sync_tenant_display_name_user_has_no_tenant():
    user = MagicMock(id=1, tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = sync_tenant_display_name(user_id=1, company_brand="Acme")

    assert result == "Acme"


def test_sync_tenant_display_name_tenant_missing():
    user = MagicMock(id=1, tenant_id=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, None]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = sync_tenant_display_name(user_id=1, company_brand="Acme")

    assert result == "Acme"


def test_sync_tenant_display_name_same_name_no_update():
    user = MagicMock(id=1, tenant_id=5)
    # tenant.name must be a real string so strip() works; use PropertyMock for `.name`
    tenant = MagicMock(id=5)
    tenant.name = "Acme"
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = sync_tenant_display_name(user_id=1, company_brand="Acme")

    db.commit.assert_not_called()
    assert result == "Acme"


def test_sync_tenant_display_name_updates_and_notifies():
    user = MagicMock(id=1, tenant_id=5)
    tenant = MagicMock(id=5)
    tenant.name = "OldName"
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.neuro_bus.application_neuro_bridge.neuro_notify_tenant_changed"
        ) as mock_notify:
            result = sync_tenant_display_name(user_id=1, company_brand="NewName")

    db.commit.assert_called_once()
    mock_notify.assert_called_once()
    assert result == "NewName"


# ---------------------------------------------------------------------------
# subscription_status_for_user
# ---------------------------------------------------------------------------


def test_subscription_status_user_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        status = subscription_status_for_user(999)

    assert status["active"] is False
    assert status["reason"] == "user_not_found"


def test_subscription_status_superadmin():
    user = MagicMock(id=1, role="superadmin", username="su", tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        status = subscription_status_for_user(1)

    assert status["active"] is True
    assert status["reason"] == "admin_bypass"


def test_subscription_status_paid_plan():
    future = datetime.utcnow() + timedelta(days=30)
    tenant = MagicMock(id=5, plan_id="saas-pro", trial_expires_at=future)
    user = MagicMock(id=1, role="user", username="alice", tenant_id=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=True
        ):
            status = subscription_status_for_user(1)

    assert status["active"] is True
    assert status["reason"] == "paid_plan"


def test_subscription_status_active_trial():
    future = datetime.utcnow() + timedelta(days=10)
    tenant = MagicMock(id=5, plan_id=None, trial_expires_at=future)
    user = MagicMock(id=1, role="user", username="alice", tenant_id=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=False
        ):
            status = subscription_status_for_user(1)

    assert status["active"] is True
    assert status["reason"] == "trial"
    assert status["trial_days_remaining"] >= 9


def test_subscription_status_trial_expired():
    past = datetime.utcnow() - timedelta(days=1)
    tenant = MagicMock(id=5, plan_id=None, trial_expires_at=past)
    user = MagicMock(id=1, role="user", username="alice", tenant_id=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, tenant]

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=False
        ):
            status = subscription_status_for_user(1)

    assert status["active"] is False
    assert status["reason"] == "trial_expired"


def test_subscription_status_no_tenant():
    user = MagicMock(id=1, role="user", username="alice", tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        status = subscription_status_for_user(1)

    assert status["active"] is False
    assert status["reason"] == "trial_expired"
    assert status["tenant_id"] is None


# ---------------------------------------------------------------------------
# apply_paid_plan_to_tenant
# ---------------------------------------------------------------------------


def test_apply_paid_plan_to_tenant_invalid_plan():
    with patch(
        "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=False
    ):
        result = apply_paid_plan_to_tenant(tenant_id=1, plan_id="free")
    assert result is False


def test_apply_paid_plan_to_tenant_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=True
        ):
            result = apply_paid_plan_to_tenant(tenant_id=999, plan_id="saas-pro")

    assert result is False


def test_apply_paid_plan_to_tenant_success():
    tenant = MagicMock(id=5)
    tenant.name = "Acme"
    tenant.plan_id = None
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = tenant

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.is_saas_plan_id", return_value=True
        ):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_tenant_changed"
            ) as mock_notify:
                result = apply_paid_plan_to_tenant(tenant_id=5, plan_id="saas-pro")

    assert result is True
    db.commit.assert_called_once()
    mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# apply_paid_plan_for_user
# ---------------------------------------------------------------------------


def test_apply_paid_plan_for_user_user_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = apply_paid_plan_for_user(user_id=99, plan_id="saas-pro")

    assert result is False


def test_apply_paid_plan_for_user_no_tenant():
    user = MagicMock(id=1, tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        result = apply_paid_plan_for_user(user_id=1, plan_id="saas-pro")

    assert result is False


def test_apply_paid_plan_for_user_delegates_to_tenant():
    user = MagicMock(id=1, tenant_id=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    with patch(
        "app.application.tenant_subscription_app_service.get_db", return_value=_make_db_ctx(db)
    ):
        with patch(
            "app.application.tenant_subscription_app_service.apply_paid_plan_to_tenant",
            return_value=True,
        ) as mock_apply:
            result = apply_paid_plan_for_user(user_id=1, plan_id="saas-pro")

    assert result is True
    mock_apply.assert_called_once_with(tenant_id=5, plan_id="saas-pro")
