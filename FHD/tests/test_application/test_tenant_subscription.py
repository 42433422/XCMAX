"""tenant_subscription_app_service 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.tenant_subscription_app_service import (
    _slug_code,
    provision_trial_for_user,
    subscription_status_for_user,
)


def test_slug_code_sanitizes_username() -> None:
    assert _slug_code("Acme Corp!") == "acme-corp"
    assert _slug_code("") == "tenant"


def test_provision_trial_creates_tenant() -> None:
    user = MagicMock(id=5, tenant_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [user, None]

    with patch("app.application.tenant_subscription_app_service.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db
        mock_get_db.return_value.__exit__.return_value = False
        with patch(
            "app.application.tenant_subscription_app_service.trial_days",
            return_value=14,
        ):
            tid = provision_trial_for_user(user_id=5, username="alice", display_name="Alice")

    assert tid is not None
    assert user.tenant_id is not None
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_subscription_status_admin_bypass() -> None:
    user = MagicMock(id=1, role="admin", username="root", tenant_id=None)
    with patch("app.application.tenant_subscription_app_service.get_db") as mock_get_db:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        mock_get_db.return_value.__enter__.return_value = db
        mock_get_db.return_value.__exit__.return_value = False
        status = subscription_status_for_user(1)

    assert status["active"] is True
    assert status["reason"] == "admin_bypass"
