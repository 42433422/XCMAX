"""合同到期推送单测。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.services.contract_lifecycle import notify_contract_expiry_items


@pytest.fixture
def items():
    return [
        {
            "market_user_id": 1001,
            "username": "demo",
            "end_date": "2026-07-01",
        }
    ]


@patch("app.services.user_cs_pipeline.save_pipeline")
@patch("app.services.user_cs_pipeline.load_pipeline")
def test_notify_dry_run_no_push(mock_load, mock_save, items):
    mock_load.return_value = {"market_user_id": 1001}
    out = notify_contract_expiry_items(items, dry_run=True, push=False)
    assert out["notified"] == 1
    assert out["pushed"] == 0
    mock_save.assert_not_called()


@patch(
    "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository"
)
@patch("app.services.user_cs_intake_notice._primary_contact_name", return_value="wx-contact")
@patch("app.desktop_automation.service.get_desktop_automation_service")
@patch("app.services.user_cs_pipeline.save_pipeline")
@patch("app.services.user_cs_pipeline.load_pipeline")
def test_notify_push_success(
    mock_load,
    mock_save,
    mock_desktop,
    mock_contact,
    mock_repo_factory,
    items,
):
    mock_load.return_value = {"market_user_id": 1001}
    repo = MagicMock()
    repo.was_recently_notified.return_value = False
    repo.insert_notification.return_value = {"id": 1, "push_status": "success"}
    mock_repo_factory.return_value = repo
    mock_desktop.return_value.send_wechat_message.return_value = {
        "success": True,
        "message_sent": True,
    }

    out = notify_contract_expiry_items(items, dry_run=False, push=True)
    assert out["pushed"] == 1
    assert out["failed"] == 0
    repo.insert_notification.assert_called_once()
    assert repo.insert_notification.call_args.kwargs["push_status"] == "success"


@patch(
    "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository"
)
@patch("app.services.user_cs_intake_notice._primary_contact_name", return_value="")
@patch("app.services.user_cs_pipeline.save_pipeline")
@patch("app.services.user_cs_pipeline.load_pipeline")
def test_notify_push_failed_no_contact(
    mock_load,
    mock_save,
    mock_contact,
    mock_repo_factory,
    items,
):
    mock_load.return_value = {"market_user_id": 1001}
    repo = MagicMock()
    repo.was_recently_notified.return_value = False
    repo.insert_notification.return_value = {"id": 2, "push_status": "failed"}
    mock_repo_factory.return_value = repo

    out = notify_contract_expiry_items(items, dry_run=False, push=True)
    assert out["failed"] == 1
    assert repo.insert_notification.call_args.kwargs["push_status"] == "failed"
