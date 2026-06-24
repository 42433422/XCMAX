"""真实行为测试 (第二波)：app/services/user_cs_intake_notice.py

聚焦未覆盖逻辑：
- _now_iso (line 12)
- _primary_contact_name 全分支 (16-33): intake_form company/name、erp_customer_name、
  bindings(name/contact_name)、username 兜底
- maybe_send_intake_form_notice (62-85): 已发跳过/force、无联系人错误、
  发送成功(持久化)、发送失败(不持久化)、可恢复异常分支

所有函数内 import 在真实模块路径处 patch；DB/桌面自动化全部 mock。离线确定性。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from app.services.user_cs_intake_notice import (
    _now_iso,
    _primary_contact_name,
    maybe_send_intake_form_notice,
)

# ──────────────────────────────────────────────────────────────────────────────
# _now_iso
# ──────────────────────────────────────────────────────────────────────────────


class TestNowIso:
    def test_returns_parseable_utc_iso(self):
        out = _now_iso()
        assert isinstance(out, str)
        # 可被 fromisoformat 解析且带时区 (UTC)
        parsed = datetime.fromisoformat(out)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# ──────────────────────────────────────────────────────────────────────────────
# _primary_contact_name  (函数内 import: user_cs_pipeline.load_pipeline,
#                          wechat_group_customer_bridge.get_bindings_for_user)
# ──────────────────────────────────────────────────────────────────────────────


class TestPrimaryContactName:
    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_prefers_intake_company(self, mock_load, mock_bindings):
        # intake_form.company 优先级最高
        mock_load.return_value = {
            "intake_form": {"company": "  山竹科技  ", "name": "李四"},
            "erp_customer_name": "ERP名",
            "username": "user1",
        }
        assert _primary_contact_name(7) == "山竹科技"
        mock_load.assert_called_once_with(7)
        # company 命中即返回，不应触碰 bindings
        mock_bindings.assert_not_called()

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_falls_back_to_name_when_no_company(self, mock_load, mock_bindings):
        mock_load.return_value = {"intake_form": {"company": "   ", "name": "李四"}}
        assert _primary_contact_name(1) == "李四"
        mock_bindings.assert_not_called()

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_falls_back_to_erp_name(self, mock_load, mock_bindings):
        # intake_form 不是 dict -> 走 erp_customer_name
        mock_load.return_value = {
            "intake_form": "not-a-dict",
            "erp_customer_name": "  ERP客户  ",
        }
        assert _primary_contact_name(2) == "ERP客户"
        mock_bindings.assert_not_called()

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_falls_back_to_binding_name(self, mock_load, mock_bindings):
        mock_load.return_value = {"intake_form": {}}
        mock_bindings.return_value = [{"name": "王五", "contact_name": "ignored"}]
        assert _primary_contact_name(3) == "王五"
        mock_bindings.assert_called_once_with(3)

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_binding_contact_name_when_no_name(self, mock_load, mock_bindings):
        mock_load.return_value = {"intake_form": {}}
        mock_bindings.return_value = [{"contact_name": "赵六"}]
        assert _primary_contact_name(4) == "赵六"

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_binding_first_not_dict_falls_to_username(self, mock_load, mock_bindings):
        # bindings 非空但首项不是 dict -> isinstance 分支为假 -> 兜底 username
        mock_load.return_value = {"intake_form": {}, "username": "  fallback_user  "}
        mock_bindings.return_value = ["raw-string-binding"]
        assert _primary_contact_name(5) == "fallback_user"

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_username_fallback_when_no_bindings(self, mock_load, mock_bindings):
        mock_load.return_value = {"intake_form": {}, "username": "solo"}
        mock_bindings.return_value = []
        assert _primary_contact_name(6) == "solo"

    @patch("app.services.wechat_group_customer_bridge.get_bindings_for_user")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_empty_everything_returns_empty(self, mock_load, mock_bindings):
        mock_load.return_value = {}
        mock_bindings.return_value = []
        assert _primary_contact_name(8) == ""


# ──────────────────────────────────────────────────────────────────────────────
# maybe_send_intake_form_notice
# 函数内 import: user_cs_demand_form.build_intake_form_url,
#               user_cs_pipeline.load_pipeline/save_pipeline,
#               app.desktop_automation.service.get_desktop_automation_service
# ──────────────────────────────────────────────────────────────────────────────


class TestMaybeSendIntakeFormNotice:
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_already_sent_skips(self, mock_load):
        mock_load.return_value = {"intake_form_notice_sent": True}
        result = maybe_send_intake_form_notice(1)
        assert result == {"sent": False, "skipped": True, "reason": "already_sent"}

    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_no_contact_returns_error(self, mock_load, mock_contact):
        mock_load.return_value = {}
        mock_contact.return_value = ""
        result = maybe_send_intake_form_notice(1)
        assert result["sent"] is False
        assert "未找到微信群联系人" in result["error"]

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_explicit_contact_name_used_without_lookup(
        self, mock_load, mock_save, mock_url, mock_auto
    ):
        # 显式 contact_name 不应触发 _primary_contact_name 查找
        mock_load.return_value = {}
        mock_url.return_value = "https://form.example/abc"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        with patch("app.services.user_cs_intake_notice._primary_contact_name") as mock_contact:
            result = maybe_send_intake_form_notice(9, contact_name="直接联系人", brief="需要发货")
            mock_contact.assert_not_called()
        assert result["sent"] is True
        assert result["form_url"] == "https://form.example/abc"
        # 表单 url 用显式联系人构造
        assert mock_url.call_args.kwargs["client_name"] == "直接联系人"
        assert mock_url.call_args.kwargs["brief"] == "需要发货"

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_success_persists_flags(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        doc = {"stage": "idle"}
        mock_load.return_value = doc
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/xyz"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = maybe_send_intake_form_notice(5)
        assert result["sent"] is True
        assert result["form_url"] == "https://form.example/xyz"
        assert "张三" in result["message"]
        # 成功 -> 持久化标记
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["intake_form_notice_sent"] is True
        assert saved["intake_sent"] is True
        # 发送目标联系人与文本
        send_args = mock_auto.return_value.send_wechat_message.call_args[0]
        assert send_args[0] == "张三"

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_message_sent_falls_back_to_success_key(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        # result 缺 message_sent 时回退到 success
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/q"
        mock_auto.return_value.send_wechat_message.return_value = {"success": True}
        result = maybe_send_intake_form_notice(5)
        assert result["sent"] is True
        mock_save.assert_called_once()

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_failure_does_not_persist(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/f"
        mock_auto.return_value.send_wechat_message.return_value = {"success": False}
        result = maybe_send_intake_form_notice(5)
        assert result["sent"] is False
        assert "send_result" in result
        # 失败不持久化
        mock_save.assert_not_called()

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_recoverable_exception_returns_error(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        # ConnectionError ∈ RECOVERABLE_ERRORS -> 捕获返回 error
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/e"
        mock_auto.return_value.send_wechat_message.side_effect = ConnectionError("network down")
        result = maybe_send_intake_form_notice(5)
        assert result["sent"] is False
        assert "network down" in result["error"]
        mock_save.assert_not_called()

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_force_bypasses_already_sent(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        # 已发但 force=True -> 不走 skip，继续发送
        mock_load.return_value = {"intake_form_notice_sent": True}
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/force"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = maybe_send_intake_form_notice(5, force=True)
        assert result["sent"] is True
        mock_save.assert_called_once()

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_demand_form.build_intake_form_url")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_brief_included_in_message_and_url(
        self, mock_load, mock_contact, mock_save, mock_url, mock_auto
    ):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_url.return_value = "https://form.example/b"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = maybe_send_intake_form_notice(5, brief="背景信息XYZ")
        assert "背景信息XYZ" in result["message"]
        assert mock_url.call_args.kwargs["brief"] == "背景信息XYZ"

    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_username_passed_to_load(self, mock_load):
        mock_load.return_value = {"intake_form_notice_sent": True}
        maybe_send_intake_form_notice(11, username="alice")
        mock_load.assert_called_once_with(11, username="alice")
