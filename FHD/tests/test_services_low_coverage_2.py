"""更多低覆盖率 services 测试：connected_welcome、intake_finalize、user_preference、user_service。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.user_cs_connected_welcome import maybe_send_connected_welcome
from app.services.user_cs_intake_finalize import finalize_intake_submission
from app.services.user_cs_pipeline import load_pipeline, save_pipeline, set_pipeline_stage

# ══════════════════════════════════════════════════════════════════════════════
# user_cs_connected_welcome
# ══════════════════════════════════════════════════════════════════════════════


class TestMaybeSendConnectedWelcome:
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_already_sent(self, mock_load, mock_contact):
        mock_load.return_value = {"connected_welcome_sent": True}
        result = maybe_send_connected_welcome(1)
        assert result["sent"] is False
        assert result["skipped"] is True

    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_no_contact(self, mock_load, mock_contact):
        mock_load.return_value = {}
        mock_contact.return_value = ""
        result = maybe_send_connected_welcome(1)
        assert result["sent"] is False
        assert "未找到" in result["error"]

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_send_success(self, mock_save, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {"stage": "idle"}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = maybe_send_connected_welcome(1)
        assert result["sent"] is True

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_failure(self, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {"success": False}
        result = maybe_send_connected_welcome(1)
        assert result["sent"] is False

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    def test_send_exception(self, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.side_effect = ConnectionError("network error")
        result = maybe_send_connected_welcome(1)
        assert result["sent"] is False
        assert "network error" in result["error"]

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_force_resend(self, mock_save, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {"connected_welcome_sent": True}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        result = maybe_send_connected_welcome(1, force=True)
        assert result["sent"] is True

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_stage_updated_on_success(self, mock_save, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {"stage": "idle"}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        maybe_send_connected_welcome(1)
        saved_doc = mock_save.call_args[0][0]
        assert saved_doc["stage"] == "connected"

    @patch("app.desktop_automation.service.get_desktop_automation_service")
    @patch("app.services.user_cs_intake_notice._primary_contact_name")
    @patch("app.services.user_cs_pipeline.load_pipeline")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    def test_stage_not_overwritten(self, mock_save, mock_load, mock_contact, mock_auto):
        mock_load.return_value = {"stage": "intake_done"}
        mock_contact.return_value = "张三"
        mock_auto.return_value.send_wechat_message.return_value = {
            "success": True,
            "message_sent": True,
        }
        maybe_send_connected_welcome(1)
        saved_doc = mock_save.call_args[0][0]
        assert saved_doc["stage"] == "intake_done"


# ══════════════════════════════════════════════════════════════════════════════
# user_cs_intake_finalize
# ══════════════════════════════════════════════════════════════════════════════


class TestFinalizeIntakeSubmission:
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_crm_store.sync_crm_from_pipeline_doc")
    def test_basic_finalize(self, mock_sync, mock_save):
        mock_sync.side_effect = lambda d: d
        mock_save.side_effect = lambda d: d
        doc = {"intake_form": {"company": "测试公司"}}
        result_doc, meta = finalize_intake_submission(1, doc)
        assert meta["erp_linked"] is True
        assert result_doc["erp_customer_name"] == "测试公司"

    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_crm_store.sync_crm_from_pipeline_doc")
    def test_no_company(self, mock_sync, mock_save):
        mock_sync.side_effect = lambda d: d
        mock_save.side_effect = lambda d: d
        doc = {"intake_form": {}}
        result_doc, meta = finalize_intake_submission(1, doc)
        assert meta["erp_linked"] is False

    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_crm_store.sync_crm_from_pipeline_doc")
    def test_crm_opportunity_id_set(self, mock_sync, mock_save):
        mock_sync.side_effect = lambda d: d
        mock_save.side_effect = lambda d: d
        doc = {"intake_form": {"company": "测试公司"}}
        result_doc, meta = finalize_intake_submission(1, doc)
        assert result_doc["crm_opportunity_id"] == 1

    @patch("app.services.user_cs_intake_notice.maybe_send_intake_form_notice")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_crm_store.sync_crm_from_pipeline_doc")
    def test_notify_wechat(self, mock_sync, mock_save, mock_notice):
        mock_sync.side_effect = lambda d: d
        mock_save.side_effect = lambda d: d
        mock_notice.return_value = {"sent": True}
        doc = {"intake_form": {"company": "测试公司"}}
        result_doc, meta = finalize_intake_submission(1, doc, notify_wechat=True)
        assert meta["wechat_notice"]["sent"] is True

    @patch("app.services.user_cs_intake_notice.maybe_send_intake_form_notice")
    @patch("app.services.user_cs_pipeline.save_pipeline")
    @patch("app.services.user_cs_crm_store.sync_crm_from_pipeline_doc")
    def test_notify_wechat_failure(self, mock_sync, mock_save, mock_notice):
        mock_sync.side_effect = lambda d: d
        mock_save.side_effect = lambda d: d
        mock_notice.side_effect = RuntimeError("send failed")
        doc = {"intake_form": {"company": "测试公司"}}
        # Should not raise
        result_doc, meta = finalize_intake_submission(1, doc, notify_wechat=True)
        assert meta["wechat_notice"]["sent"] is False


# ══════════════════════════════════════════════════════════════════════════════
# user_preference_service
# ══════════════════════════════════════════════════════════════════════════════


class TestUserPreferenceService:
    @patch("app.services.user_preference_service.get_db")
    def test_get_preference_found(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_pref = MagicMock()
        mock_pref.preference_value = "dark"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_pref
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.get_preference("user1", "theme")
        assert result == "dark"

    @patch("app.services.user_preference_service.get_db")
    def test_get_preference_not_found(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.get_preference("user1", "theme")
        assert result is None

    @patch("app.services.user_preference_service.get_db")
    def test_set_preference_update_existing(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_pref = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_pref
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.set_preference("user1", "theme", "light")
        assert result is True
        mock_db.commit.assert_called_once()

    @patch("app.services.user_preference_service.get_db")
    def test_set_preference_create_new(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.set_preference("user1", "theme", "dark")
        assert result is True
        mock_db.add.assert_called_once()

    @patch("app.services.user_preference_service.get_db")
    def test_get_all_preferences(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        p1 = MagicMock()
        p1.preference_key = "theme"
        p1.preference_value = "dark"
        p2 = MagicMock()
        p2.preference_key = "lang"
        p2.preference_value = "zh"
        mock_db.query.return_value.filter.return_value.all.return_value = [p1, p2]
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.get_all_preferences("user1")
        assert result == {"theme": "dark", "lang": "zh"}

    @patch("app.services.user_preference_service.get_db")
    def test_delete_preference_found(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 1
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.delete_preference("user1", "theme")
        assert result is True

    @patch("app.services.user_preference_service.get_db")
    def test_delete_preference_not_found(self, mock_get_db):
        from app.services.user_preference_service import UserPreferenceService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 0
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserPreferenceService()
        result = svc.delete_preference("user1", "theme")
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# user_service
# ══════════════════════════════════════════════════════════════════════════════


class TestUserService:
    @patch("app.services.user_service.get_db")
    def test_list_users(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "test"
        mock_user.display_name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True
        mock_user.created_by = None
        mock_user.created_at = None
        mock_user.last_login = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_user
        ]
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.list_users()
        assert len(result) == 1
        assert result[0]["username"] == "test"

    @patch("app.services.user_service.get_db")
    def test_get_user_found(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "test"
        mock_user.display_name = "Test"
        mock_user.email = ""
        mock_user.role = "viewer"
        mock_user.is_active = True
        mock_user.created_by = None
        mock_user.created_at = None
        mock_user.last_login = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.get_user(1)
        assert result is not None
        assert result["username"] == "test"

    @patch("app.services.user_service.get_db")
    def test_get_user_not_found(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.get_user(999)
        assert result is None

    @patch("app.services.user_service.get_db")
    def test_create_user_duplicate(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_existing = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_existing
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.create_user("existing", "pass")
        assert result["success"] is False
        assert "已存在" in result["message"]

    @patch("app.services.user_service.generate_password_hash")
    @patch("app.services.user_service.get_db")
    def test_create_user_success(self, mock_get_db, mock_hash):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "newuser"
        mock_user.display_name = "New"
        mock_user.email = ""
        mock_user.role = "viewer"
        mock_user.is_active = True
        mock_user.created_by = None
        mock_user.created_at = None
        mock_user.last_login = None
        mock_hash.return_value = "hashed"

        def mock_refresh(u):
            u.id = 1

        mock_db.refresh = mock_refresh
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.create_user("newuser", "pass")
        assert result["success"] is True

    @patch("app.services.user_service.get_db")
    def test_update_user_not_found(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.update_user(999, display_name="New")
        assert result["success"] is False

    @patch("app.services.user_service.get_db")
    def test_delete_user_not_found(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.delete_user(999)
        assert result["success"] is False

    @patch("app.services.user_service.get_db")
    def test_delete_user_success(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.delete_user(1)
        assert result["success"] is True
        assert mock_user.is_active is False

    @patch("app.services.user_service.get_db")
    def test_get_user_by_username(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "test"
        mock_user.display_name = "Test"
        mock_user.email = ""
        mock_user.role = "viewer"
        mock_user.is_active = True
        mock_user.created_by = None
        mock_user.created_at = None
        mock_user.last_login = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.get_user_by_username("test")
        assert result is not None
        assert result["username"] == "test"

    @patch("app.services.user_service.get_db")
    def test_get_user_by_username_not_found(self, mock_get_db):
        from app.services.user_service import UserService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = UserService()
        result = svc.get_user_by_username("nonexistent")
        assert result is None
