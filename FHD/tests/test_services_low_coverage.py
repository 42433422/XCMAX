"""低覆盖率 services 模块测试：CS 客服流程、微信桥接、偏好、用户服务。"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.user_cs_crm_store import (
    CrmSyncError,
    get_crm_bundle_for_market_user,
    sync_crm_from_pipeline_doc,
)
from app.services.user_cs_delivery import (
    apply_contract_snapshot_to_doc,
    build_delivery_progress_message,
    ensure_delivery_on_doc,
    update_delivery_plan,
)
from app.services.user_cs_demand_form import (
    _landing_base_url,
    build_intake_form_url,
    verify_webhook_secret,
)
from app.services.user_cs_enterprise_credentials import (
    _base_payload,
    issue_enterprise_credentials,
)
from app.services.user_cs_intake_notice import build_intake_form_notice_message
from app.services.user_cs_landing_crm import apply_landing_submission_to_funnel
from app.services.user_cs_software_delivery import notify_software_delivery

# ══════════════════════════════════════════════════════════════════════════════
# user_cs_delivery
# ══════════════════════════════════════════════════════════════════════════════


class TestEnsureDeliveryOnDoc:
    def test_creates_delivery_structure(self):
        doc = {}
        result = ensure_delivery_on_doc(doc)
        assert "delivery" in result
        assert result["delivery"]["milestones"] == []
        assert result["delivery"]["status"] == "planned"
        assert "payment" in result
        assert "invoice" in result

    def test_preserves_existing(self):
        doc = {"delivery": {"status": "in_progress", "milestones": [{"done": True}]}}
        result = ensure_delivery_on_doc(doc)
        assert result["delivery"]["status"] == "in_progress"

    def test_non_dict_delivery_replaced(self):
        doc = {"delivery": "invalid"}
        result = ensure_delivery_on_doc(doc)
        assert isinstance(result["delivery"], dict)


class TestUpdateDeliveryPlan:
    def test_update_expected_delivery(self):
        doc = {}
        result = update_delivery_plan(doc, expected_delivery_at="2026-12-31")
        assert result["delivery"]["expected_delivery_at"] == "2026-12-31"

    def test_update_milestones(self):
        milestones = [{"name": "phase1", "done": True}]
        result = update_delivery_plan({}, milestones=milestones)
        assert result["delivery"]["milestones"] == milestones

    def test_start_delivery(self):
        result = update_delivery_plan({}, start_delivery=True)
        assert result["delivery"]["status"] == "in_progress"
        assert "started_at" in result["delivery"]

    def test_empty_expected_delivery_ignored(self):
        result = update_delivery_plan({}, expected_delivery_at="  ")
        assert "expected_delivery_at" not in result.get("delivery", {})


class TestApplyContractSnapshotToDoc:
    def test_updates_contract_fields(self):
        doc = {}
        result = apply_contract_snapshot_to_doc(doc, {"total_amount_number": "1000"})
        assert result["contract_fields"]["total_amount_number"] == "1000"

    def test_none_values_skipped(self):
        result = apply_contract_snapshot_to_doc({}, {"key": None})
        assert "key" not in result.get("contract_fields", {})

    def test_payment_amount_parsed(self):
        result = apply_contract_snapshot_to_doc({}, {"total_amount_number": "100.50"})
        assert result["payment"]["contract_amount_cents"] == 10050

    def test_invalid_amount_ignored(self):
        result = apply_contract_snapshot_to_doc({}, {"total_amount_number": "abc"})
        assert "contract_amount_cents" not in result.get("payment", {})


class TestBuildDeliveryProgressMessage:
    def test_basic_message(self):
        doc = {"delivery": {"status": "in_progress"}, "erp_customer_name": "测试公司"}
        msg = build_delivery_progress_message(doc)
        assert "测试公司" in msg
        assert "in_progress" in msg

    def test_with_expected_delivery(self):
        doc = {"delivery": {"status": "planned", "expected_delivery_at": "2026-12-31T00:00:00"}}
        msg = build_delivery_progress_message(doc)
        assert "2026-12-31" in msg

    def test_with_milestones(self):
        doc = {
            "delivery": {
                "status": "in_progress",
                "milestones": [{"done": True}, {"done": False}],
            }
        }
        msg = build_delivery_progress_message(doc)
        assert "1/2" in msg

    def test_client_name_override(self):
        doc = {"delivery": {"status": "planned"}}
        msg = build_delivery_progress_message(doc, client_name="自定义客户")
        assert "自定义客户" in msg


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_demand_form
# ══════════════════════════════════════════════════════════════════════════════


class TestLandingBaseUrl:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_LANDING_BASE_URL", raising=False)
        assert _landing_base_url() == "https://xiu-ci.com"

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_LANDING_BASE_URL", "https://custom.com/")
        assert _landing_base_url() == "https://custom.com"

    def test_explicit_base(self, monkeypatch):
        assert _landing_base_url("https://explicit.com/") == "https://explicit.com"


class TestBuildIntakeFormUrl:
    def test_basic_url(self, monkeypatch):
        monkeypatch.delenv("XCAGI_LANDING_BASE_URL", raising=False)
        url = build_intake_form_url(123)
        assert "market_user_id=123" in url
        assert "contact.html" in url

    def test_with_client_name(self, monkeypatch):
        monkeypatch.delenv("XCAGI_LANDING_BASE_URL", raising=False)
        url = build_intake_form_url(123, client_name="测试公司")
        assert "client=" in url

    def test_with_brief(self, monkeypatch):
        monkeypatch.delenv("XCAGI_LANDING_BASE_URL", raising=False)
        url = build_intake_form_url(123, brief="需要发货")
        assert "brief=" in url


class TestVerifyWebhookSecret:
    def test_no_secret_set(self, monkeypatch):
        monkeypatch.delenv("INTAKE_WEBHOOK_SECRET", raising=False)
        assert verify_webhook_secret("anything") is True

    def test_matching_secret(self, monkeypatch):
        monkeypatch.setenv("INTAKE_WEBHOOK_SECRET", "mysecret")
        assert verify_webhook_secret("mysecret") is True

    def test_mismatched_secret(self, monkeypatch):
        monkeypatch.setenv("INTAKE_WEBHOOK_SECRET", "mysecret")
        assert verify_webhook_secret("wrong") is False

    def test_none_header(self, monkeypatch):
        monkeypatch.setenv("INTAKE_WEBHOOK_SECRET", "mysecret")
        assert verify_webhook_secret(None) is False


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_enterprise_credentials
# ══════════════════════════════════════════════════════════════════════════════


class TestBasePayload:
    def test_empty_doc(self):
        result = _base_payload({})
        assert result["username"] == ""
        assert result["password"] == ""
        assert result["password_recorded"] is False
        assert result["is_enterprise"] is False

    def test_with_data(self):
        doc = {
            "username": "testuser",
            "enterprise_login_password": "secret",
            "enterprise_credentials_issued_at": "2026-01-01",
            "enterprise_login_email": "test@example.com",
            "enterprise_auto_provisioned_at": "2026-01-01",
        }
        result = _base_payload(doc)
        assert result["username"] == "testuser"
        assert result["password_recorded"] is True
        assert result["is_enterprise"] is True

    def test_username_fallback(self):
        result = _base_payload({}, username="fallback_user")
        assert result["username"] == "fallback_user"


class TestIssueEnterpriseCredentials:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_issues_credentials(self, mock_save, mock_load):
        mock_load.return_value = {"username": "testuser"}
        mock_save.return_value = {"username": "testuser"}
        result = issue_enterprise_credentials(1, username="testuser")
        assert result["success"] is True
        assert "password" in result

    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_custom_password(self, mock_save, mock_load):
        mock_load.return_value = {"username": "testuser"}
        mock_save.return_value = {"username": "testuser"}
        result = issue_enterprise_credentials(1, username="testuser", password="custom_pwd")
        assert result["password"] == "custom_pwd"


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_crm_store
# ══════════════════════════════════════════════════════════════════════════════


class TestCrmSyncError:
    def test_message(self):
        err = CrmSyncError("sync failed", details="connection timeout")
        assert str(err) == "sync failed"
        assert err.details == "connection timeout"


class TestGetCrmBundleForMarketUser:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_empty_pipeline(self, mock_load):
        mock_load.return_value = {}
        result = get_crm_bundle_for_market_user(1)
        assert result["opportunity"] is None
        assert result["quote"] is None
        assert result["invoice"] is None

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_with_opportunity(self, mock_load):
        mock_load.return_value = {
            "crm_opportunity_id": 10,
            "landing_contact_id": 5,
            "erp_customer_name": "测试公司",
        }
        result = get_crm_bundle_for_market_user(1)
        assert result["opportunity"] is not None
        assert result["opportunity"]["id"] == 10

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_with_quote(self, mock_load):
        mock_load.return_value = {
            "crm_quote_id": 20,
            "quote_draft": {"status": "draft", "summary": "测试报价"},
        }
        result = get_crm_bundle_for_market_user(1)
        assert result["quote"] is not None
        assert result["quote"]["status"] == "draft"


class TestSyncCrmFromPipelineDoc:
    def test_adds_synced_at(self):
        doc = {"updated_at": "2026-01-01"}
        result = sync_crm_from_pipeline_doc(doc)
        assert result["crm_funnel_synced_at"] == "2026-01-01"

    def test_preserves_existing(self):
        doc = {"crm_funnel_synced_at": "existing", "updated_at": "2026-01-01"}
        result = sync_crm_from_pipeline_doc(doc)
        assert result["crm_funnel_synced_at"] == "existing"


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_intake_notice
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildIntakeFormNoticeMessage:
    def test_basic_message(self):
        msg = build_intake_form_notice_message(
            contact_name="张三", form_url="https://example.com/form"
        )
        assert "张三" in msg
        assert "https://example.com/form" in msg

    def test_with_brief(self):
        msg = build_intake_form_notice_message(
            contact_name="张三", form_url="https://example.com/form", brief="需要发货单"
        )
        assert "需要发货单" in msg

    def test_empty_contact(self):
        msg = build_intake_form_notice_message(contact_name="", form_url="https://example.com/form")
        assert "您好" in msg


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_landing_crm
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyLandingSubmissionToFunnel:
    @patch("app.services.user_cs_demand_form.apply_landing_submission_to_pipeline")
    def test_anonymous_lead(self, mock_apply):
        result = apply_landing_submission_to_funnel({"market_user_id": 0})
        assert result["anonymous_lead"] is True

    @patch("app.services.user_cs_intake_finalize.finalize_intake_submission")
    @patch("app.services.user_cs_demand_form.apply_landing_submission_to_pipeline")
    def test_valid_user_no_crm_sync(self, mock_apply, mock_finalize):
        mock_apply.return_value = {
            "intake_submitted_at": "2026-01-01",
            "crm_funnel_synced_at": "2026-01-01",
        }
        result = apply_landing_submission_to_funnel({"market_user_id": 1})
        assert "intake_submitted_at" in result

    @patch("app.services.user_cs_intake_finalize.finalize_intake_submission")
    @patch("app.services.user_cs_demand_form.apply_landing_submission_to_pipeline")
    def test_valid_user_needs_crm_sync(self, mock_apply, mock_finalize):
        mock_apply.return_value = {"intake_submitted_at": "2026-01-01"}
        mock_finalize.return_value = (
            {"intake_submitted_at": "2026-01-01", "crm_funnel_synced_at": "2026-01-01"},
            {},
        )
        result = apply_landing_submission_to_funnel({"market_user_id": 1})
        mock_finalize.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_software_delivery
# ══════════════════════════════════════════════════════════════════════════════


class TestNotifySoftwareDelivery:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    def test_already_sent(self, mock_contact, mock_load):
        mock_load.return_value = {"software_delivery_sent_at": "2026-01-01"}
        result = notify_software_delivery(1)
        assert result["skipped"] is True

    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    def test_no_contact(self, mock_contact, mock_load):
        mock_load.return_value = {}
        mock_contact.return_value = ""
        result = notify_software_delivery(1)
        assert result["success"] is False
        assert "未绑定" in result["error"]

    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.desktop_automation.service.get_desktop_automation_service")
    def test_send_success(self, mock_auto, mock_contact, mock_load, mock_save):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = notify_software_delivery(1)
        assert result["success"] is True

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_failure(self, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {"success": False}
        result = notify_software_delivery(1)
        assert result["success"] is False

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_exception(self, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.side_effect = ConnectionError("network error")
        result = notify_software_delivery(1)
        assert result["success"] is False
        assert "network error" in result["error"]
