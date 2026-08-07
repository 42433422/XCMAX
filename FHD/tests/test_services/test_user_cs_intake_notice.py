"""测试内部客服需求采集话术模块（user_cs_intake_notice）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.user_cs_intake_notice import (
    _now_iso,
    _primary_contact_name,
    build_intake_form_notice_message,
    maybe_send_intake_form_notice,
)


class TestNowIso:
    def test_returns_iso_string(self) -> None:
        result = _now_iso()
        assert isinstance(result, str)
        assert "T" in result and result.endswith("+00:00")


class TestPrimaryContactName:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_company_preferred(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "intake_form": {"company": " 某某科技 ", "name": ""},
            "erp_customer_name": "ERP名",
            "username": "u1",
        }
        assert _primary_contact_name(1) == "某某科技"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_name_fallback(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "intake_form": {"company": "", "name": "张三"},
            "erp_customer_name": "ERP名",
            "username": "u1",
        }
        assert _primary_contact_name(1) == "张三"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_non_dict_intake_falls_back(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "intake_form": "not-a-dict",
            "erp_customer_name": "ERP名",
            "username": "u1",
        }
        assert _primary_contact_name(1) == "ERP名"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_erp_fallback(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"intake_form": {}, "erp_customer_name": "  ERP名  "}
        assert _primary_contact_name(1) == "ERP名"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_username_fallback(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"intake_form": {}, "erp_customer_name": "", "username": "u1"}
        assert _primary_contact_name(1) == "u1"


class TestBuildIntakeFormNoticeMessage:
    def test_basic_message(self) -> None:
        text = build_intake_form_notice_message(
            contact_name=" 李四 ", form_url="https://example.com/form"
        )
        assert "李四" in text
        assert "https://example.com/form" in text
        assert "审核码" in text

    def test_empty_contact_uses_default(self) -> None:
        text = build_intake_form_notice_message(contact_name="   ", form_url="http://f")
        assert "您好" in text

    def test_with_brief(self) -> None:
        text = build_intake_form_notice_message(
            contact_name="王五", form_url="http://f", brief="  需要定制方案  "
        )
        assert "背景：需要定制方案" in text


class TestMaybeSendIntakeFormNotice:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_already_sent_skips(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"intake_form_notice_sent": True}
        result = maybe_send_intake_form_notice(1)
        assert result == {"sent": False, "skipped": True, "reason": "already_sent"}

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_no_contact_returns_error(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"intake_form_notice_sent": False}
        result = maybe_send_intake_form_notice(1)
        assert result["sent"] is False
        assert "error" in result

    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_success(
        self,
        mock_load: MagicMock,
        mock_save: MagicMock,
        mock_da: MagicMock,
        mock_url: MagicMock,
    ) -> None:
        mock_load.return_value = {"intake_form_notice_sent": False}
        mock_url.return_value = "http://form"
        auto = MagicMock()
        auto.send_wechat_message.return_value = {"success": True, "message_sent": True}
        mock_da.return_value = auto
        result = maybe_send_intake_form_notice(1, contact_name="张三")
        assert result["sent"] is True
        assert "form_url" in result
        mock_save.assert_called_once()

    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_failure_not_saved(
        self,
        mock_load: MagicMock,
        mock_save: MagicMock,
        mock_da: MagicMock,
        mock_url: MagicMock,
    ) -> None:
        mock_load.return_value = {"intake_form_notice_sent": False}
        mock_url.return_value = "http://form"
        auto = MagicMock()
        auto.send_wechat_message.return_value = {"success": False}
        mock_da.return_value = auto
        result = maybe_send_intake_form_notice(1, contact_name="张三")
        assert result["sent"] is False
        mock_save.assert_not_called()

    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_exception(
        self, mock_load: MagicMock, mock_da: MagicMock, mock_url: MagicMock
    ) -> None:
        mock_load.return_value = {"intake_form_notice_sent": False}
        mock_url.return_value = "http://form"
        auto = MagicMock()
        auto.send_wechat_message.side_effect = RuntimeError("boom")
        mock_da.return_value = auto
        result = maybe_send_intake_form_notice(1, contact_name="张三")
        assert result["sent"] is False
        assert "boom" in result["error"]
